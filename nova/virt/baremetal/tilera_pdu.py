# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 University of Southern California / ISI
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
Class for PDU power manager.
"""

import subprocess
import time

from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova import utils
from nova.virt.baremetal import baremetal_states
from nova.virt.baremetal import base

tilera_pdu_opts = [
    cfg.StrOpt('tile_pdu_ip',
               default='10.0.100.1',
               help='ip address of tilera pdu'),
    cfg.StrOpt('tile_pdu_mgr',
               default='/tftboot/pdu_mgr',
               help='management script for tilera pdu'),
    cfg.IntOpt('tile_pdu_off',
               default=2,
               help='power status of tilera PDU is OFF'),
    cfg.IntOpt('tile_pdu_on',
               default=1,
               help='power status of tilera PDU is ON'),
    cfg.IntOpt('tile_power_retry',
               default=3,
               help='maximum number of retries for tilera power operations'),
    cfg.IntOpt('tile_power_wait',
               default=90,
               help='wait time in seconds until check the result '
                    'after tilera power operations'),
    ]

CONF = cfg.CONF
CONF.register_opts(tilera_pdu_opts)
CONF.import_opt('tile_service_wait', 'nova.virt.baremetal.tilera')
CONF.import_opt('baremetal_tftp_root', 'nova.virt.baremetal.driver')

LOG = logging.getLogger(__name__)


class PduError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message

    def __str__(self):
        return "%s: %s" % (self.status, self.message)


class Pdu(base.PowerManager):

    def __init__(self, node):
        self._address = node['pm_address']
        self._node_id = node['id']
        if self._address == None:
            raise PduError(-1, _("address is None"))
        if self._node_id == None:
            raise PduError(-1, _("node_id is None"))

    def _exec_status(self):
        LOG.debug(_("Before ping to the bare-metal node"))
        tile_output = CONF.baremetal_tftp_root + "/tile_output_" + \
                    str(self._node_id)
        grep_cmd = ("ping -c1 " + self._address + " | grep Unreachable > " +
                    tile_output)
        subprocess.Popen(grep_cmd, shell=True)
        time.sleep(CONF.tile_service_wait)
        file = open(tile_output, "r")
        out = file.readline().find("Unreachable")
        utils.execute('rm', tile_output, run_as_root=True)
        return out

    def activate_node(self):
        state = self._power_on()
        return state

    def reboot_node(self):
        self._power_off()
        state = self._power_on()
        return state

    def deactivate_node(self):
        state = self._power_off()
        return state

    def _power_mgr(self, mode):
        """
        Changes power state of the given node.

        According to the mode (1-ON, 2-OFF, 3-REBOOT), power state can be
        changed. /tftpboot/pdu_mgr script handles power management of
        PDU (Power Distribution Unit).
        """
        utils.execute(CONF.tile_pdu_mgr, CONF.tile_pdu_ip,
                      str(mode), '>>', 'pdu_output')

    def _power_on(self):
        count = 1
        self._power_mgr(CONF.tile_pdu_off)
        self._power_mgr(CONF.tile_pdu_on)
        time.sleep(CONF.tile_power_wait)
        while not self.is_power_on():
            count += 1
            if count > CONF.tile_power_retry:
                LOG.exception(_("power_on failed"))
                return baremetal_states.ERROR
            self._power_mgr(CONF.tile_pdu_off)
            self._power_mgr(CONF.tile_pdu_on)
            time.sleep(CONF.tile_power_wait)
        return baremetal_states.ACTIVE

    def _power_off(self):
        try:
            self._power_mgr(CONF.tile_pdu_off)
        except Exception:
            LOG.exception(_("power_off failed"))
            return baremetal_states.ERROR
        return baremetal_states.DELETED

    def _is_power_off(self):
        r = self._exec_status()
        return (r != -1)

    def is_power_on(self):
        r = self._exec_status()
        return (r == -1)

    def start_console(self):
        pass

    def stop_console(self):
        pass
