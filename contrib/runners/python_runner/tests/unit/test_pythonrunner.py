# Licensed to the StackStorm, Inc ('StackStorm') under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import re

import mock
from oslo_config import cfg

import python_runner
from st2actions.container.base import RunnerContainer
from st2common.runners.python_action_wrapper import PythonActionWrapper
from st2common.runners.base_action import Action
from st2common.runners.utils import get_action_class_instance
from st2common.services import config as config_service
from st2common.constants.action import ACTION_OUTPUT_RESULT_DELIMITER
from st2common.constants.action import LIVEACTION_STATUS_SUCCEEDED, LIVEACTION_STATUS_FAILED
from st2common.constants.action import LIVEACTION_STATUS_TIMED_OUT
from st2common.constants.pack import SYSTEM_PACK_NAME
from st2common.persistence.execution import ActionExecutionOutput
from st2tests.base import RunnerTestCase
from st2tests.base import CleanDbTestCase
from st2tests.base import blocking_eventlet_spawn
from st2tests.base import make_mock_stream_readline
import st2tests.base as tests_base


PASCAL_ROW_ACTION_PATH = os.path.join(tests_base.get_resources_path(), 'packs',
                                      'pythonactions/actions/pascal_row.py')
TEST_ACTION_PATH = os.path.join(tests_base.get_resources_path(), 'packs',
                                'pythonactions/actions/test.py')
PATHS_ACTION_PATH = os.path.join(tests_base.get_resources_path(), 'packs',
                                'pythonactions/actions/python_paths.py')
ACTION_1_PATH = os.path.join(tests_base.get_fixtures_path(),
                             'packs/dummy_pack_9/actions/list_repos_doesnt_exist.py')
ACTION_2_PATH = os.path.join(tests_base.get_fixtures_path(),
                             'packs/dummy_pack_9/actions/invalid_syntax.py')
NON_SIMPLE_TYPE_ACTION = os.path.join(tests_base.get_resources_path(), 'packs',
                                      'pythonactions/actions/non_simple_type.py')

# Note: runner inherits parent args which doesn't work with tests since test pass additional
# unrecognized args
mock_sys = mock.Mock()
mock_sys.argv = []

MOCK_EXECUTION = mock.Mock()
MOCK_EXECUTION.id = '598dbf0c0640fd54bffc688b'


@mock.patch('python_runner.sys', mock_sys)
class PythonRunnerTestCase(RunnerTestCase, CleanDbTestCase):
    register_packs = True
    register_pack_configs = True

    def test_runner_creation(self):
        runner = python_runner.get_runner()
        self.assertTrue(runner is not None, 'Creation failed. No instance.')
        self.assertEqual(type(runner), python_runner.PythonRunner, 'Creation failed. No instance.')

    def test_action_returns_non_serializable_result(self):
        # Actions returns non-simple type which can't be serialized, verify result is simple str()
        # representation of the result
        runner = self._get_mock_runner_obj()
        runner.entry_point = NON_SIMPLE_TYPE_ACTION
        runner.pre_run()
        (status, output, _) = runner.run({})

        self.assertEqual(status, LIVEACTION_STATUS_SUCCEEDED)
        self.assertTrue(output is not None)

        expected_result_re = (r"\[{'a': '1'}, {'h': 3, 'c': 2}, {'e': "
                              "<non_simple_type.Test object at .*?>}\]")
        match = re.match(expected_result_re, output['result'])
        self.assertTrue(match)

    def test_simple_action_with_result_no_status(self):
        runner = self._get_mock_runner_obj()
        runner.entry_point = PASCAL_ROW_ACTION_PATH
        runner.pre_run()
        (status, output, _) = runner.run({'row_index': 5})
        self.assertEqual(status, LIVEACTION_STATUS_SUCCEEDED)
        self.assertTrue(output is not None)
        self.assertEqual(output['result'], [1, 5, 10, 10, 5, 1])

    def test_simple_action_with_result_as_None_no_status(self):
        runner = self._get_mock_runner_obj()
        runner.entry_point = PASCAL_ROW_ACTION_PATH
        runner.pre_run()
        (status, output, _) = runner.run({'row_index': 'b'})
        self.assertEqual(status, LIVEACTION_STATUS_SUCCEEDED)
        self.assertTrue(output is not None)
        self.assertEqual(output['exit_code'], 0)
        self.assertEqual(output['result'], None)

    def test_simple_action_timeout(self):
        timeout = 0
        runner = self._get_mock_runner_obj()
        runner.runner_parameters = {python_runner.RUNNER_TIMEOUT: timeout}
        runner.entry_point = PASCAL_ROW_ACTION_PATH
        runner.pre_run()
        (status, output, _) = runner.run({'row_index': 4})
        self.assertEqual(status, LIVEACTION_STATUS_TIMED_OUT)
        self.assertTrue(output is not None)
        self.assertEqual(output['result'], 'None')
        self.assertEqual(output['error'], 'Action failed to complete in 0 seconds')
        self.assertEqual(output['exit_code'], -9)

    def test_simple_action_with_status_succeeded(self):
        runner = self._get_mock_runner_obj()
        runner.entry_point = PASCAL_ROW_ACTION_PATH
        runner.pre_run()
        (status, output, _) = runner.run({'row_index': 4})
        self.assertEqual(status, LIVEACTION_STATUS_SUCCEEDED)
        self.assertTrue(output is not None)
        self.assertEqual(output['result'], [1, 4, 6, 4, 1])

    def test_simple_action_with_status_failed(self):
        runner = self._get_mock_runner_obj()
        runner.entry_point = PASCAL_ROW_ACTION_PATH
        runner.pre_run()
        (status, output, _) = runner.run({'row_index': 'a'})
        self.assertEqual(status, LIVEACTION_STATUS_FAILED)
        self.assertTrue(output is not None)
        self.assertEqual(output['result'], "This is suppose to fail don't worry!!")

    def test_simple_action_with_status_complex_type_returned_for_result(self):
        # Result containing a complex type shouldn't break the returning a tuple with status
        # behavior
        runner = self._get_mock_runner_obj()
        runner.entry_point = PASCAL_ROW_ACTION_PATH
        runner.pre_run()
        (status, output, _) = runner.run({'row_index': 'complex_type'})

        self.assertEqual(status, LIVEACTION_STATUS_FAILED)
        self.assertTrue(output is not None)
        self.assertTrue('<pascal_row.PascalRowAction object at' in output['result'])

    def test_simple_action_with_status_failed_result_none(self):
        runner = self._get_mock_runner_obj()
        runner.entry_point = PASCAL_ROW_ACTION_PATH
        runner.pre_run()
        (status, output, _) = runner.run({'row_index': 'c'})
        self.assertEqual(status, LIVEACTION_STATUS_FAILED)
        self.assertTrue(output is not None)
        self.assertEqual(output['result'], None)

    def test_exception_in_simple_action_with_invalid_status(self):
        runner = self._get_mock_runner_obj()
        runner.entry_point = PASCAL_ROW_ACTION_PATH
        runner.pre_run()
        self.assertRaises(ValueError,
                          runner.run, action_parameters={'row_index': 'd'})

    def test_simple_action_no_status_backward_compatibility(self):
        runner = self._get_mock_runner_obj()
        runner.entry_point = PASCAL_ROW_ACTION_PATH
        runner.pre_run()
        (status, output, _) = runner.run({'row_index': 'e'})
        self.assertEqual(status, LIVEACTION_STATUS_SUCCEEDED)
        self.assertTrue(output is not None)
        self.assertEqual(output['result'], [1, 2])

    def test_simple_action_config_value_provided_overriden_in_datastore(self):
        pack = 'dummy_pack_5'
        user = 'joe'

        # No values provided in the datastore
        runner = self._get_mock_runner_obj_from_container(pack=pack, user=user)

        self.assertEqual(runner._config['api_key'], 'some_api_key')  # static value
        self.assertEqual(runner._config['regions'], ['us-west-1'])  # static value
        self.assertEqual(runner._config['api_secret'], None)
        self.assertEqual(runner._config['private_key_path'], None)

        # api_secret overriden in the datastore (user scoped value)
        config_service.set_datastore_value_for_config_key(pack_name='dummy_pack_5',
                                                          key_name='api_secret',
                                                          user='joe',
                                                          value='foosecret',
                                                          secret=True)

        # private_key_path overriden in the datastore (global / non-user scoped value)
        config_service.set_datastore_value_for_config_key(pack_name='dummy_pack_5',
                                                          key_name='private_key_path',
                                                          value='foopath')

        runner = self._get_mock_runner_obj_from_container(pack=pack, user=user)
        self.assertEqual(runner._config['api_key'], 'some_api_key')  # static value
        self.assertEqual(runner._config['regions'], ['us-west-1'])  # static value
        self.assertEqual(runner._config['api_secret'], 'foosecret')
        self.assertEqual(runner._config['private_key_path'], 'foopath')

    def test_simple_action_fail(self):
        runner = self._get_mock_runner_obj()
        runner.entry_point = PASCAL_ROW_ACTION_PATH
        runner.pre_run()
        (status, result, _) = runner.run({'row_index': '4'})
        self.assertTrue(result is not None)
        self.assertEqual(status, LIVEACTION_STATUS_FAILED)

    def test_simple_action_no_file(self):
        runner = self._get_mock_runner_obj()
        runner.entry_point = 'foo.py'
        runner.pre_run()
        (status, result, _) = runner.run({})
        self.assertTrue(result is not None)
        self.assertEqual(status, LIVEACTION_STATUS_FAILED)

    def test_simple_action_no_entry_point(self):
        runner = self._get_mock_runner_obj()
        runner.entry_point = ''

        expected_msg = 'Action .*? is missing entry_point attribute'
        self.assertRaisesRegexp(Exception, expected_msg, runner.run, {})

    @mock.patch('st2common.util.green.shell.subprocess.Popen')
    def test_action_with_user_supplied_env_vars(self, mock_popen):
        env_vars = {'key1': 'val1', 'key2': 'val2', 'PYTHONPATH': 'foobar'}

        mock_process = mock.Mock()
        mock_process.communicate.return_value = ('', '')
        mock_popen.return_value = mock_process

        runner = self._get_mock_runner_obj()
        runner.runner_parameters = {'env': env_vars}
        runner.entry_point = PASCAL_ROW_ACTION_PATH
        runner.pre_run()
        (_, _, _) = runner.run({'row_index': 4})

        _, call_kwargs = mock_popen.call_args
        actual_env = call_kwargs['env']

        for key, value in env_vars.items():
            # Verify that a blacklsited PYTHONPATH has been filtered out
            if key == 'PYTHONPATH':
                self.assertTrue(actual_env[key] != value)
            else:
                self.assertEqual(actual_env[key], value)

    @mock.patch('st2common.util.green.shell.subprocess.Popen')
    @mock.patch('st2common.util.green.shell.eventlet.spawn')
    def test_action_stdout_and_stderr_is_not_stored_in_db_by_default(self, mock_spawn, mock_popen):
        # Feature should be disabled by default
        values = {'delimiter': ACTION_OUTPUT_RESULT_DELIMITER}

        # Note: We need to mock spawn function so we can test everything in single event loop
        # iteration
        mock_spawn.side_effect = blocking_eventlet_spawn

        # No output to stdout and no result (implicit None)
        mock_stdout = [
            'pre result line 1\n',
            '%(delimiter)sTrue%(delimiter)s' % values,
            'post result line 1'
        ]
        mock_stderr = [
            'stderr line 1\n',
            'stderr line 2\n',
            'stderr line 3\n'
        ]

        mock_process = mock.Mock()
        mock_process.returncode = 0
        mock_popen.return_value = mock_process
        mock_process.stdout.closed = False
        mock_process.stderr.closed = False
        mock_process.stdout.readline = make_mock_stream_readline(mock_process.stdout, mock_stdout,
                                                                 stop_counter=3)
        mock_process.stderr.readline = make_mock_stream_readline(mock_process.stderr, mock_stderr,
                                                                 stop_counter=3)

        runner = self._get_mock_runner_obj()
        runner.entry_point = PASCAL_ROW_ACTION_PATH
        runner.pre_run()
        (_, output, _) = runner.run({'row_index': 4})

        self.assertEqual(output['stdout'], 'pre result line 1\npost result line 1')
        self.assertEqual(output['stderr'], 'stderr line 1\nstderr line 2\nstderr line 3\n')
        self.assertEqual(output['result'], 'True')
        self.assertEqual(output['exit_code'], 0)

        output_dbs = ActionExecutionOutput.get_all()
        self.assertEqual(len(output_dbs), 0)

        # False is a default behavior so end result should be the same
        cfg.CONF.set_override(name='stream_output', group='actionrunner', override=False)

        mock_process = mock.Mock()
        mock_process.returncode = 0
        mock_popen.return_value = mock_process
        mock_process.stdout.closed = False
        mock_process.stderr.closed = False
        mock_process.stdout.readline = make_mock_stream_readline(mock_process.stdout, mock_stdout,
                                                                 stop_counter=3)
        mock_process.stderr.readline = make_mock_stream_readline(mock_process.stderr, mock_stderr,
                                                                 stop_counter=3)

        runner.pre_run()
        (_, output, _) = runner.run({'row_index': 4})

        self.assertEqual(output['stdout'], 'pre result line 1\npost result line 1')
        self.assertEqual(output['stderr'], 'stderr line 1\nstderr line 2\nstderr line 3\n')
        self.assertEqual(output['result'], 'True')
        self.assertEqual(output['exit_code'], 0)

        output_dbs = ActionExecutionOutput.get_all()
        self.assertEqual(len(output_dbs), 0)

    @mock.patch('st2common.util.green.shell.subprocess.Popen')
    @mock.patch('st2common.util.green.shell.eventlet.spawn')
    def test_action_stdout_and_stderr_is_stored_in_the_db(self, mock_spawn, mock_popen):
        # Feature is enabled
        cfg.CONF.set_override(name='stream_output', group='actionrunner', override=True)

        values = {'delimiter': ACTION_OUTPUT_RESULT_DELIMITER}

        # Note: We need to mock spawn function so we can test everything in single event loop
        # iteration
        mock_spawn.side_effect = blocking_eventlet_spawn

        # No output to stdout and no result (implicit None)
        mock_stdout = [
            'pre result line 1\n',
            'pre result line 2\n',
            '%(delimiter)sTrue%(delimiter)s' % values,
            'post result line 1'
        ]
        mock_stderr = [
            'stderr line 1\n',
            'stderr line 2\n',
            'stderr line 3\n'
        ]

        mock_process = mock.Mock()
        mock_process.returncode = 0
        mock_popen.return_value = mock_process
        mock_process.stdout.closed = False
        mock_process.stderr.closed = False
        mock_process.stdout.readline = make_mock_stream_readline(mock_process.stdout, mock_stdout,
                                                                 stop_counter=4)
        mock_process.stderr.readline = make_mock_stream_readline(mock_process.stderr, mock_stderr,
                                                                 stop_counter=3)

        runner = self._get_mock_runner_obj()
        runner.entry_point = PASCAL_ROW_ACTION_PATH
        runner.pre_run()
        (_, output, _) = runner.run({'row_index': 4})

        self.assertEqual(output['stdout'],
                         'pre result line 1\npre result line 2\npost result line 1')
        self.assertEqual(output['stderr'], 'stderr line 1\nstderr line 2\nstderr line 3\n')
        self.assertEqual(output['result'], 'True')
        self.assertEqual(output['exit_code'], 0)

        # Verify stdout and stderr lines have been correctly stored in the db
        # Note - result delimiter should not be stored in the db
        output_dbs = ActionExecutionOutput.query(output_type='stdout')
        self.assertEqual(len(output_dbs), 3)
        self.assertEqual(output_dbs[0].runner_ref, 'python-script')
        self.assertEqual(output_dbs[0].data, mock_stdout[0])
        self.assertEqual(output_dbs[1].data, mock_stdout[1])
        self.assertEqual(output_dbs[2].data, mock_stdout[3])

        output_dbs = ActionExecutionOutput.query(output_type='stderr')
        self.assertEqual(len(output_dbs), 3)
        self.assertEqual(output_dbs[0].runner_ref, 'python-script')
        self.assertEqual(output_dbs[0].data, mock_stderr[0])
        self.assertEqual(output_dbs[1].data, mock_stderr[1])
        self.assertEqual(output_dbs[2].data, mock_stderr[2])

    @mock.patch('st2common.util.green.shell.subprocess.Popen')
    def test_stdout_interception_and_parsing(self, mock_popen):
        values = {'delimiter': ACTION_OUTPUT_RESULT_DELIMITER}

        # No output to stdout and no result (implicit None)
        mock_stdout = ['%(delimiter)sNone%(delimiter)s' % values]
        mock_stderr = ['foo stderr']

        mock_process = mock.Mock()
        mock_process.returncode = 0
        mock_popen.return_value = mock_process
        mock_process.stdout.closed = False
        mock_process.stderr.closed = False
        mock_process.stdout.readline = make_mock_stream_readline(mock_process.stdout, mock_stdout)
        mock_process.stderr.readline = make_mock_stream_readline(mock_process.stderr, mock_stderr)

        runner = self._get_mock_runner_obj()
        runner.entry_point = PASCAL_ROW_ACTION_PATH
        runner.pre_run()
        (_, output, _) = runner.run({'row_index': 4})

        self.assertEqual(output['stdout'], '')
        self.assertEqual(output['stderr'], mock_stderr[0])
        self.assertEqual(output['result'], 'None')
        self.assertEqual(output['exit_code'], 0)

        # Output to stdout, no result (implicit None), return_code 1 and status failed
        mock_stdout = ['pre result%(delimiter)sNone%(delimiter)spost result' % values]
        mock_stderr = ['foo stderr']

        mock_process = mock.Mock()
        mock_process.returncode = 1
        mock_popen.return_value = mock_process
        mock_process.stdout.closed = False
        mock_process.stderr.closed = False
        mock_process.stdout.readline = make_mock_stream_readline(mock_process.stdout, mock_stdout)
        mock_process.stderr.readline = make_mock_stream_readline(mock_process.stderr, mock_stderr)

        runner = self._get_mock_runner_obj()
        runner.entry_point = PASCAL_ROW_ACTION_PATH
        runner.pre_run()
        (status, output, _) = runner.run({'row_index': 4})

        self.assertEqual(output['stdout'], 'pre resultpost result')
        self.assertEqual(output['stderr'], mock_stderr[0])
        self.assertEqual(output['result'], 'None')
        self.assertEqual(output['exit_code'], 1)
        self.assertEqual(status, 'failed')

        # Output to stdout, no result (implicit None), return_code 1 and status succeeded
        mock_stdout = ['pre result%(delimiter)sNone%(delimiter)spost result' % values]
        mock_stderr = ['foo stderr']

        mock_process = mock.Mock()
        mock_process.returncode = 0
        mock_popen.return_value = mock_process
        mock_process.stdout.closed = False
        mock_process.stderr.closed = False
        mock_process.stdout.readline = make_mock_stream_readline(mock_process.stdout, mock_stdout)
        mock_process.stderr.readline = make_mock_stream_readline(mock_process.stderr, mock_stderr)

        runner = self._get_mock_runner_obj()
        runner.entry_point = PASCAL_ROW_ACTION_PATH
        runner.pre_run()
        (status, output, _) = runner.run({'row_index': 4})

        self.assertEqual(output['stdout'], 'pre resultpost result')
        self.assertEqual(output['stderr'], mock_stderr[0])
        self.assertEqual(output['result'], 'None')
        self.assertEqual(output['exit_code'], 0)
        self.assertEqual(status, 'succeeded')

    @mock.patch('st2common.util.green.shell.subprocess.Popen')
    def test_common_st2_env_vars_are_available_to_the_action(self, mock_popen):
        mock_process = mock.Mock()
        mock_process.communicate.return_value = ('', '')
        mock_popen.return_value = mock_process

        runner = self._get_mock_runner_obj()
        runner.auth_token = mock.Mock()
        runner.auth_token.token = 'ponies'
        runner.entry_point = PASCAL_ROW_ACTION_PATH
        runner.pre_run()
        (_, _, _) = runner.run({'row_index': 4})

        _, call_kwargs = mock_popen.call_args
        actual_env = call_kwargs['env']
        self.assertCommonSt2EnvVarsAvailableInEnv(env=actual_env)

    def test_action_class_instantiation_action_service_argument(self):
        class Action1(Action):
            # Constructor not overriden so no issue here
            pass

            def run(self):
                pass

        class Action2(Action):
            # Constructor overriden, but takes action_service argument
            def __init__(self, config, action_service=None):
                super(Action2, self).__init__(config=config,
                                              action_service=action_service)

            def run(self):
                pass

        class Action3(Action):
            # Constructor overriden, but doesn't take to action service
            def __init__(self, config):
                super(Action3, self).__init__(config=config)

            def run(self):
                pass

        config = {'a': 1, 'b': 2}
        action_service = 'ActionService!'

        action1 = get_action_class_instance(action_cls=Action1, config=config,
                                            action_service=action_service)
        self.assertEqual(action1.config, config)
        self.assertEqual(action1.action_service, action_service)

        action2 = get_action_class_instance(action_cls=Action2, config=config,
                                            action_service=action_service)
        self.assertEqual(action2.config, config)
        self.assertEqual(action2.action_service, action_service)

        action3 = get_action_class_instance(action_cls=Action3, config=config,
                                            action_service=action_service)
        self.assertEqual(action3.config, config)
        self.assertEqual(action3.action_service, action_service)

    def test_action_with_same_module_name_as_module_in_stdlib(self):
        runner = self._get_mock_runner_obj()
        runner.entry_point = TEST_ACTION_PATH
        runner.pre_run()
        (status, output, _) = runner.run({})
        self.assertEqual(status, LIVEACTION_STATUS_SUCCEEDED)
        self.assertTrue(output is not None)
        self.assertEqual(output['result'], 'test action')

    def test_python_action_wrapper_script_doesnt_get_added_to_sys_path(self):
        # Validate that the directory where python_action_wrapper.py script is located
        # (st2common/runners) doesn't get added to sys.path
        runner = self._get_mock_runner_obj()
        runner.entry_point = PATHS_ACTION_PATH
        runner.pre_run()
        (status, output, _) = runner.run({})

        self.assertEqual(status, LIVEACTION_STATUS_SUCCEEDED)
        self.assertTrue(output is not None)

        lines = output['stdout'].split('\n')
        process_sys_path = lines[0]
        process_pythonpath = lines[1]

        assert 'sys.path' in process_sys_path
        assert 'PYTHONPATH' in process_pythonpath

        wrapper_script_path = 'st2common/runners'

        assertion_msg = 'Found python wrapper script path in subprocess path'
        self.assertTrue(wrapper_script_path not in process_sys_path, assertion_msg)
        self.assertTrue(wrapper_script_path not in process_pythonpath, assertion_msg)

    def test_python_action_wrapper_action_script_file_doesnt_exist_friendly_error(self):
        # File in a directory which is not a Python package
        wrapper = PythonActionWrapper(pack='dummy_pack_5', file_path='/tmp/doesnt.exist',
                                      user='joe')

        expected_msg = 'File "/tmp/doesnt.exist" has no action class or the file doesn\'t exist.'
        self.assertRaisesRegexp(Exception, expected_msg, wrapper._get_action_instance)

        # File in a directory which is a Python package
        wrapper = PythonActionWrapper(pack='dummy_pack_5', file_path=ACTION_1_PATH,
                                      user='joe')

        expected_msg = ('Failed to load action class from file ".*?list_repos_doesnt_exist.py" '
                       '\(action file most likely doesn\'t exist or contains invalid syntax\): '
                       '\[Errno 2\] No such file or directory')
        self.assertRaisesRegexp(Exception, expected_msg, wrapper._get_action_instance)

    def test_python_action_wrapper_action_script_file_contains_invalid_syntax_friendly_error(self):
        wrapper = PythonActionWrapper(pack='dummy_pack_5', file_path=ACTION_2_PATH,
                                      user='joe')
        expected_msg = ('Failed to load action class from file ".*?invalid_syntax.py" '
                       '\(action file most likely doesn\'t exist or contains invalid syntax\): '
                       'No module named invalid')
        self.assertRaisesRegexp(Exception, expected_msg, wrapper._get_action_instance)

    def test_simple_action_log_messages_and_log_level_runner_param(self):
        expected_msg_1 = 'st2.actions.python.PascalRowAction: INFO     test info log message'
        expected_msg_2 = 'st2.actions.python.PascalRowAction: DEBUG    test debug log message'
        expected_msg_3 = 'st2.actions.python.PascalRowAction: ERROR    test error log message'

        runner = self._get_mock_runner_obj()
        runner.entry_point = PASCAL_ROW_ACTION_PATH
        runner.pre_run()
        (status, output, _) = runner.run({'row_index': 'e'})
        self.assertEqual(status, LIVEACTION_STATUS_SUCCEEDED)
        self.assertTrue(output is not None)
        self.assertEqual(output['result'], [1, 2])

        self.assertTrue(expected_msg_1 in output['stderr'])
        self.assertTrue(expected_msg_2 in output['stderr'])
        self.assertTrue(expected_msg_3 in output['stderr'])

        # Only log messages with level info and above should be displayed
        runner = self._get_mock_runner_obj()
        runner.entry_point = PASCAL_ROW_ACTION_PATH
        runner.runner_parameters = {
            'log_level': 'info'
        }
        runner.pre_run()
        (status, output, _) = runner.run({'row_index': 'e'})
        self.assertEqual(status, LIVEACTION_STATUS_SUCCEEDED)
        self.assertTrue(output is not None)
        self.assertEqual(output['result'], [1, 2])

        self.assertTrue(expected_msg_1 in output['stderr'])
        self.assertFalse(expected_msg_2 in output['stderr'])
        self.assertTrue(expected_msg_3 in output['stderr'])

        # Only log messages with level error and above should be displayed
        runner = self._get_mock_runner_obj()
        runner.entry_point = PASCAL_ROW_ACTION_PATH
        runner.runner_parameters = {
            'log_level': 'error'
        }
        runner.pre_run()
        (status, output, _) = runner.run({'row_index': 'e'})
        self.assertEqual(status, LIVEACTION_STATUS_SUCCEEDED)
        self.assertTrue(output is not None)
        self.assertEqual(output['result'], [1, 2])

        self.assertFalse(expected_msg_1 in output['stderr'])
        self.assertFalse(expected_msg_2 in output['stderr'])
        self.assertTrue(expected_msg_3 in output['stderr'])

    def _get_mock_runner_obj(self):
        runner = python_runner.get_runner()
        runner.execution = MOCK_EXECUTION
        runner.action = self._get_mock_action_obj()
        runner.runner_parameters = {}

        return runner

    @mock.patch('st2actions.container.base.ActionExecution.get', mock.Mock())
    def _get_mock_runner_obj_from_container(self, pack, user):
        container = RunnerContainer()

        runnertype_db = mock.Mock()
        runnertype_db.runner_module = 'python_runner'
        action_db = mock.Mock()
        action_db.pack = pack
        action_db.entry_point = 'foo.py'
        liveaction_db = mock.Mock()
        liveaction_db.id = '123'
        liveaction_db.context = {'user': user}
        runner = container._get_runner(runnertype_db=runnertype_db, action_db=action_db,
                                       liveaction_db=liveaction_db)
        runner.execution = MOCK_EXECUTION
        runner.action = self._get_mock_action_obj()
        runner.runner_parameters = {}

        return runner

    def _get_mock_action_obj(self):
        """
        Return mock action object.

        Pack gets set to the system pack so the action doesn't require a separate virtualenv.
        """
        action = mock.Mock()
        action.ref = 'dummy.action'
        action.pack = SYSTEM_PACK_NAME
        action.entry_point = 'foo.py'
        action.runner_type = {
            'name': 'python-script'
        }
        return action
