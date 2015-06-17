# -*- coding: utf-8 -*-
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

import re
import os.path
from pip.req import parse_requirements
from setuptools import setup, find_packages


def fetch_requirements():
    links = []
    reqs = []
    for req in parse_requirements('requirements.txt', session=False):
        if req.link:
            links.append(str(req.link))
        reqs.append(str(req.req))
    return (reqs, links)


current_dir = os.path.dirname(os.path.realpath(__file__))
version_file = os.path.join(current_dir, '../st2client/st2client/__init__.py')
with open(version_file, 'r') as f:
    vmatch = re.search(r'__version__ = [\'\"](.*)[\'\"]$', f.read(), flags=re.MULTILINE)


install_reqs, dep_links = fetch_requirements()
ST2_COMPONENT = os.path.basename(current_dir)
ST2_VERSION = vmatch.group(1)


setup(
    name=ST2_COMPONENT,
    version=ST2_VERSION,
    description='{} component'.format(ST2_COMPONENT),
    author='StackStorm',
    author_email='info@stackstorm.com',
    install_requires=install_reqs,
    dependency_links=dep_links,
    test_suite=ST2_COMPONENT,
    zip_safe=False,
    include_package_data=True,
    packages=find_packages(exclude=['setuptools'])
)
