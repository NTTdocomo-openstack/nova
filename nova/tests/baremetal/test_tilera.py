# Copyright (c) 2011 University of Southern California / ISI
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
Tests for baremetal tilera driver.
"""

import mox

from nova import exception
from nova import test

from nova.virt.baremetal import tilera


class BaremetalTILERATestCase(test.TestCase):

    def test_init(self):
        self.flags(
                tile_monitor="x",
                )
        tilera.TILERA()

        self.flags(
                tile_monitor="",
                )
        self.assertRaises(exception.NovaException, tilera.TILERA)
