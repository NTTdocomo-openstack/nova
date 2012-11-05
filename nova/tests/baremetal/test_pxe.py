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
Tests for baremetal pxe driver.
"""

import mox

from nova import exception
from nova import flags
from nova import test

from nova.virt.baremetal import pxe

FLAGS = flags.FLAGS


class BaremetalPXETestCase(test.TestCase):

    def test_random_alnum(self):
        s = pxe._random_alnum(10)
        self.assertEqual(len(s), 10)
        s = pxe._random_alnum(100)
        self.assertEqual(len(s), 100)

    def test_get_deploy_aki_id(self):
        p = pxe.PXE()
        with_kernel = {"properties": {"deploy_kernel_id": "123"}}
        without_kernel = {"properties": {}}

        self.flags(baremetal_deploy_kernel="x")
        kernel = p._get_deploy_aki_id(with_kernel)
        self.assertEqual(kernel, "123")
        kernel = p._get_deploy_aki_id(without_kernel)
        self.assertEqual(kernel, "x")

        self.flags(baremetal_deploy_kernel=None)
        kernel = p._get_deploy_aki_id(with_kernel)
        self.assertEqual(kernel, "123")
        kernel = p._get_deploy_aki_id(without_kernel)
        self.assertTrue(kernel is None)

    def test_get_deploy_ari_id(self):
        p = pxe.PXE()

        with_ramdisk = {"properties": {"deploy_ramdisk_id": "123"}}
        without_ramdisk = {"properties": {}}

        self.flags(baremetal_deploy_ramdisk="x")
        ramdisk = p._get_deploy_ari_id(with_ramdisk)
        self.assertEqual(ramdisk, "123")
        ramdisk = p._get_deploy_ari_id(without_ramdisk)
        self.assertEqual(ramdisk, "x")

        self.flags(baremetal_deploy_ramdisk=None)
        ramdisk = p._get_deploy_ari_id(with_ramdisk)
        self.assertEqual(ramdisk, "123")
        ramdisk = p._get_deploy_ari_id(without_ramdisk)
        self.assertTrue(ramdisk is None)
