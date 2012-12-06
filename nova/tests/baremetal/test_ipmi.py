# Copyright (c) 2012 NTT DOCOMO, INC.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Tests for bare-metal ipmi driver.
"""

import os
import stat
import time

import mox

from nova.openstack.common import cfg
from nova import test
from nova import utils as nova_utils

from nova.tests.baremetal.db import utils
from nova.virt.baremetal import baremetal_states
from nova.virt.baremetal import ipmi
from nova.virt.baremetal import utils as bm_utils
from nova.virt.libvirt import utils as libvirt_utils

CONF = cfg.CONF


class BareMetalIPMITestCase(test.TestCase):

    def setUp(self):
        super(BareMetalIPMITestCase, self).setUp()
        self.node = utils.new_bm_node(
                id=123,
                pm_address='fake-address',
                pm_user='fake-user',
                pm_password='fake-password')
        self.ipmi = ipmi.Ipmi(self.node)

    def test_construct(self):
        self.assertEqual(self.ipmi._node_id, 123)
        self.assertEqual(self.ipmi._address, 'fake-address')
        self.assertEqual(self.ipmi._user, 'fake-user')
        self.assertEqual(self.ipmi._password, 'fake-password')

    def test_make_password_file(self):
        path = ipmi._make_password_file(self.node['pm_password'])
        try:
            self.assertTrue(os.path.isfile(path))
            self.assertEqual(os.stat(path)[stat.ST_MODE] & 0777, 0600)
            with open(path, "r") as f:
                s = f.read()
            self.assertEqual(s, self.node['pm_password'])
        finally:
            os.unlink(path)

    def test_exec_ipmitool(self):
        pwfile = '/tmp/password_file'

        self.mox.StubOutWithMock(ipmi, '_make_password_file')
        self.mox.StubOutWithMock(nova_utils, 'execute')
        self.mox.StubOutWithMock(bm_utils, 'unlink_without_raise')
        ipmi._make_password_file(self.ipmi._password).AndReturn(pwfile)
        args = [
                'ipmitool',
                '-I', 'lanplus',
                '-H', self.ipmi._address,
                '-U', self.ipmi._user,
                '-f', pwfile,
                'A', 'B', 'C',
                ]
        nova_utils.execute(*args, attempts=3).AndReturn(('', ''))
        bm_utils.unlink_without_raise(pwfile).AndReturn(None)
        self.mox.ReplayAll()

        i = ipmi.Ipmi(self.node)
        i._exec_ipmitool('A B C')
        self.mox.VerifyAll()

    def test_power_on(self):
        retry = 10
        wait = 60
        self.flags(baremetal_ipmi_power_retry=retry,
                   baremetal_ipmi_power_wait=wait)

        self.mox.StubOutWithMock(self.ipmi, '_is_power')
        self.mox.StubOutWithMock(self.ipmi, '_exec_ipmitool')
        self.mox.StubOutWithMock(time, 'sleep')
        for _ in xrange(retry):
            self.ipmi._is_power("on").AndReturn(False)
            self.ipmi._exec_ipmitool("power on")
            time.sleep(wait)
        self.ipmi._is_power("on").AndReturn(False)
        self.mox.ReplayAll()
        ret = self.ipmi._power("on")
        self.assertEqual(baremetal_states.ERROR, ret)

    def test_power_off(self):
        retry = 10
        wait = 60
        self.flags(baremetal_ipmi_power_retry=retry,
                   baremetal_ipmi_power_wait=wait)

        self.mox.StubOutWithMock(self.ipmi, '_is_power')
        self.mox.StubOutWithMock(self.ipmi, '_exec_ipmitool')
        self.mox.StubOutWithMock(time, 'sleep')
        for _ in xrange(retry):
            self.ipmi._is_power("off").AndReturn(False)
            self.ipmi._exec_ipmitool("power off")
            time.sleep(wait)
        self.ipmi._is_power("off").AndReturn(False)
        self.mox.ReplayAll()
        ret = self.ipmi._power("off")
        self.assertEqual(baremetal_states.ERROR, ret)

    def test_console_pid(self):
        pidfile = ipmi._console_pidfile(self.node['id'])

        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(libvirt_utils, 'load_file')
        os.path.exists(pidfile).AndReturn(True)
        libvirt_utils.load_file(pidfile).AndReturn('12345')
        self.mox.ReplayAll()

        pid = ipmi._console_pid(self.node['id'])
        self.assertEqual(pid, 12345)

    def test_console_pid_nan(self):
        pidfile = ipmi._console_pidfile(self.node['id'])

        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(libvirt_utils, 'load_file')
        os.path.exists(pidfile).AndReturn(True)
        libvirt_utils.load_file(pidfile).AndReturn('***')
        self.mox.ReplayAll()

        pid = ipmi._console_pid(self.node['id'])
        self.assertTrue(pid is None)

    def test_console_pid_file_not_found(self):
        pidfile = ipmi._console_pidfile(self.node['id'])

        self.mox.StubOutWithMock(os.path, 'exists')
        os.path.exists(pidfile).AndReturn(False)
        self.mox.ReplayAll()

        pid = ipmi._console_pid(self.node['id'])
        self.assertTrue(pid is None)
