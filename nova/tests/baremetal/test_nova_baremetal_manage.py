# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright (c) 2012 NTT DOCOMO, INC.
#    Copyright 2011 OpenStack LLC
#    Copyright 2011 Ilya Alekseyev
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

import imp
import os
import sys

from nova import context
from nova import test
from nova.virt.baremetal import db as bmdb


TOPDIR = os.path.normpath(os.path.join(
                            os.path.dirname(os.path.abspath(__file__)),
                            os.pardir,
                            os.pardir,
                            os.pardir))
BM_MAN_PATH = os.path.join(TOPDIR, 'bin', 'nova-baremetal-manage')

sys.dont_write_bytecode = True
bm_man = imp.load_source('bm_man', BM_MAN_PATH)
sys.dont_write_bytecode = False


class BareMetalDbCommandsTestCase(test.TestCase):
    def setUp(self):
        super(BareMetalDbCommandsTestCase, self).setUp()
        self.flags(baremetal_sql_connection='sqlite:///:memory:')
        self.commands = bm_man.BareMetalDbCommands()

    def test_sync_and_version(self):
        self.commands.sync()
        v = self.commands.version()
        self.assertTrue(v > 0)


class BareMetalNodeCommandsTestCase(test.TestCase):
    def setUp(self):
        super(BareMetalNodeCommandsTestCase, self).setUp()
        self.flags(baremetal_sql_connection='sqlite:///:memory:')
        self.commands = bm_man.BareMetalNodeCommands()
        self.context = context.get_admin_context()
        self.stubs.Set(context, "get_admin_context", lambda: self.context)
        self.node = {"host": "host",
                     "cpus": 8,
                     "memory_mb": 8192,
                     "local_gb": 128,
                     "pm_address": "10.1.2.3",
                     "pm_user": "pm_user",
                     "pm_password": "pm_pass",
                     "prov_mac_address": "12:34:56:78:90:ab",
                     "prov_vlan_id": 1234,
                     "terminal_port": 8000,
                     }

    def test_create(self):
        values = {
            'service_host': "host",
            'cpus': 8,
            'memory_mb': 8192,
            'local_gb': 128,
            'pm_address': "10.1.2.3",
            'pm_user': "pm_user",
            'pm_password': "pm_pass",
            'prov_mac_address': "12:34:56:78:90:ab",
            'prov_vlan_id': 1234,
            'terminal_port': 8000,
            'registration_status': 'done',
            'task_state': None,
        }
        self.mox.StubOutWithMock(bmdb, "bm_node_create")
        bmdb.bm_node_create(self.context, values).AndReturn({'id': 123})
        self.mox.ReplayAll()
        self.commands.create(**self.node)

    def test_delete(self):
        self.mox.StubOutWithMock(bmdb, "bm_node_destroy")
        bmdb.bm_node_destroy(self.context, 12345)
        self.mox.ReplayAll()
        self.commands.delete(node_id=12345)


class BareMetalInterfaceCommandsTestCase(test.TestCase):
    def setUp(self):
        super(BareMetalInterfaceCommandsTestCase, self).setUp()
        self.flags(baremetal_sql_connection='sqlite:///:memory:')
        self.commands = bm_man.BareMetalInterfaceCommands()
        self.context = context.get_admin_context()
        self.stubs.Set(context, "get_admin_context", lambda: self.context)

    def test_create(self):
        self.mox.StubOutWithMock(bmdb, "bm_node_get")
        self.mox.StubOutWithMock(bmdb, "bm_interface_create")
        bmdb.bm_node_get(self.context, 12345).\
                AndReturn({'id': 12345,
                           'prov_mac_address': '12:34:56:78:90:ab'})
        bmdb.bm_interface_create(self.context,
                                 bm_node_id=12345,
                                 address="12:34:56:78:90:cd",
                                 datapath_id="0xabc",
                                 port_no="123").AndReturn(1)
        self.mox.ReplayAll()
        self.commands.create(12345,
                             "12:34:56:78:90:cd",
                             "abc",
                             "123")

    def test_delete(self):
        self.mox.StubOutWithMock(bmdb, "bm_interface_destroy")
        bmdb.bm_interface_destroy(self.context, 12345)
        self.mox.ReplayAll()
        self.commands.delete(if_id=12345)


class BareMetalPxeIpCommandsTestCase(test.TestCase):
    def setUp(self):
        super(BareMetalPxeIpCommandsTestCase, self).setUp()
        self.flags(baremetal_sql_connection='sqlite:///:memory:')
        self.commands = bm_man.BareMetalPxeIpCommands()
        self.context = context.get_admin_context()
        self.stubs.Set(context, "get_admin_context", lambda: self.context)

    def test_create(self):
        self.mox.StubOutWithMock(bmdb, "bm_pxe_ip_create")
        bmdb.bm_pxe_ip_create(self.context, "10.1.1.1", "10.1.1.2")
        bmdb.bm_pxe_ip_create(self.context, "10.1.1.3", "10.1.1.4")
        bmdb.bm_pxe_ip_create(self.context, "10.1.1.5", "10.1.1.6")
        self.mox.ReplayAll()
        self.commands.create(cidr_str="10.1.1.0/29")

    def test_delete_by_id(self):
        self.mox.StubOutWithMock(bmdb, "bm_pxe_ip_destroy")
        bmdb.bm_pxe_ip_destroy(self.context, 12345)
        self.mox.ReplayAll()
        self.commands.delete(ip_id=12345)

    def test_delete_by_cidr(self):
        self.mox.StubOutWithMock(bmdb, "bm_pxe_ip_destroy_by_address")
        bmdb.bm_pxe_ip_destroy_by_address(self.context, "10.1.1.1")
        bmdb.bm_pxe_ip_destroy_by_address(self.context, "10.1.1.3")
        bmdb.bm_pxe_ip_destroy_by_address(self.context, "10.1.1.5")
        self.mox.ReplayAll()
        self.commands.delete(cidr_str="10.1.1.0/29")
