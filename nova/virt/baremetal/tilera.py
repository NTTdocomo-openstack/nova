# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
Class for TILERA bare-metal nodes.
"""

import base64
import os
import shutil
import subprocess
import time

from nova import exception
from nova.openstack.common import cfg
from nova.openstack.common import fileutils
from nova.openstack.common import log as logging
from nova import utils
from nova.virt.baremetal import base
from nova.virt.baremetal import utils as bm_utils
from nova.virt.disk import api as disk

tilera_opts = [
    cfg.StrOpt('tile_monitor',
               default='/usr/local/TileraMDE/bin/tile-monitor',
               help='Tilera command line program for Bare-metal driver'),
    cfg.IntOpt('tile_service_wait',
               default=3,
               help='wait time in seconds until check the result '
                    'after tilera service operations'),
    ]

CONF = cfg.CONF
CONF.register_opts(tilera_opts)

LOG = logging.getLogger(__name__)


def get_baremetal_nodes():
    return TILERA()


Template = None


def _late_load_cheetah():
    global Template
    if Template is None:
        t = __import__('Cheetah.Template', globals(), locals(),
                       ['Template'], -1)
        Template = t.Template


class TILERA(base.NodeDriver):

    def __init__(self):
        if not CONF.tile_monitor:
            raise exception.NovaException(
                    'tile_monitor is not defined')

    def define_vars(self, instance, network_info, block_device_info):
        var = {}
        var['image_root'] = os.path.join(CONF.instances_path,
                                         instance['name'])
        var['tftp_root'] = CONF.baremetal_tftp_root
        var['network_info'] = network_info
        var['block_device_info'] = block_device_info
        return var

    def _inject_to_image(self, context, target, node, inst, network_info,
                         injected_files=None, admin_password=None):
        # For now, we assume that if we're not using a kernel, we're using a
        # partitioned disk image where the target partition is the first
        # partition
        target_partition = None
        if not inst['kernel_id']:
            target_partition = "1"

        if inst['key_data']:
            key = str(inst['key_data'])
        else:
            key = None

        nets = []
        for (ifc_num, (network_ref, mapping)) in enumerate(network_info):
            address = mapping['ips'][0]['ip']
            netmask = mapping['ips'][0]['netmask']
            address_v6 = None
            gateway_v6 = None
            netmask_v6 = None
            if CONF.use_ipv6:
                address_v6 = mapping['ip6s'][0]['ip']
                netmask_v6 = mapping['ip6s'][0]['netmask']
                gateway_v6 = mapping['gateway_v6']
            name = 'eth%d' % ifc_num
            net_info = {'name': name,
                   'address': address,
                   'netmask': netmask,
                   'gateway': mapping['gateway'],
                   'broadcast': mapping['broadcast'],
                   'dns': ' '.join(mapping['dns']),
                   'address_v6': address_v6,
                   'gateway_v6': gateway_v6,
                   'netmask_v6': netmask_v6,
                   'hwaddress': mapping['mac']}
            nets.append(net_info)

        ifc_template = open(CONF.baremetal_injected_network_template).read()
        _late_load_cheetah()
        net = str(Template(ifc_template,
                           searchList=[{'interfaces': nets,
                                        'use_ipv6': CONF.use_ipv6,
                                        }]))
        bootif_name = "eth%d" % len(network_info)
        net += "\n"
        net += "auto %s\n" % bootif_name
        net += "iface %s inet dhcp\n" % bootif_name

        admin_password = None

        metadata = inst.get('metadata')
        if any((key, net, metadata, admin_password)):
            inst_name = inst['name']

            img_id = inst['image_ref']

            for injection in ('metadata', 'key', 'net', 'admin_password'):
                if locals()[injection]:
                    LOG.info(_('instance %(inst_name)s: injecting '
                               '%(injection)s into image %(img_id)s'),
                             locals(), instance=inst)
            try:
                disk.inject_data(target,
                                 key, net, metadata, admin_password,
                                 files=injected_files,
                                 partition=target_partition,
                                 use_cow=False)

            except Exception as e:
                # This could be a windows image, or a vmdk format disk
                LOG.warn(_('instance %(inst_name)s: ignoring error injecting'
                        ' data into image %(img_id)s (%(e)s)') % locals(),
                         instance=inst)

    def create_image(self, var, context, image_meta, node, instance,
                     injected_files=None, admin_password=None):
        image_root = var['image_root']
        network_info = var['network_info']

        ami_id = str(image_meta['id'])
        fileutils.ensure_tree(image_root)
        image_path = os.path.join(image_root, 'disk')
        LOG.debug(_("fetching image id=%(ami_id)s target=%(image_path)s"),
                  locals())

        bm_utils.cache_image(context=context,
                             target=image_path,
                             image_id=ami_id,
                             user_id=instance['user_id'],
                             project_id=instance['project_id'])
        LOG.debug(_("injecting to image id=%(ami_id)s target=%(image_path)s"),
                  locals())
        self._inject_to_image(context, image_path, node, instance,
                              network_info,
                              injected_files=injected_files,
                              admin_password=admin_password)
        var['image_path'] = image_path
        LOG.debug(_("fetching images all done"))

    def destroy_images(self, var, context, node, instance):
        image_root = var['image_root']
        shutil.rmtree(image_root, ignore_errors=True)

    def activate_bootloader(self, var, context, node, instance, image_meta):
        tftp_root = var['tftp_root']
        image_root = var['image_root']
        disk_path = os.path.join(image_root, 'disk')
        image_path = tftp_root + "/disk_" + str(node['id'])
        target_path = tftp_root + "/fs_" + str(node['id'])
        utils.execute('mv', disk_path, image_path, run_as_root=True)
        utils.execute('mount', '-o', 'loop', image_path, target_path,
                      run_as_root=True)

    def deactivate_bootloader(self, var, context, node, instance):
        tftp_root = var['tftp_root']
        image_path = tftp_root + "/disk_" + str(node['id'])
        utils.execute('/usr/sbin/rpc.mountd', run_as_root=True)
        try:
            utils.execute('umount', '-f', image_path, run_as_root=True)
            utils.execute('rm', '-f', image_path, run_as_root=True)
        except Exception:
            LOG.debug(_("rootfs is already removed"))

    def _network_set(self, node_ip, mac_address, ip_address):
        """
        Sets network configuration based on the given ip and mac address.

        User can access the bare-metal node using ssh.
        """
        cmd = (CONF.tile_monitor +
               " --resume --net " + node_ip + " --run - " +
               "ifconfig xgbe0 hw ether " + mac_address +
               " - --wait --run - ifconfig xgbe0 " + ip_address +
               " - --wait --quit")
        LOG.debug(_("_network_set: cmd=%s"), cmd)
        subprocess.Popen(cmd, shell=True)
        time.sleep(CONF.tile_service_wait)

    def _ssh_set(self, node_ip):
        """
        Sets and Runs sshd in the node.
        """
        cmd = (CONF.tile_monitor +
               " --resume --net " + node_ip + " --run - " +
               "/usr/sbin/sshd - --wait --quit")
        LOG.debug(_("_ssh_set: cmd=%s"), cmd)
        subprocess.Popen(cmd, shell=True)
        time.sleep(CONF.tile_service_wait)

    def _iptables_set(self, var, node_ip, user_data):
        """
        Sets security setting (iptables:port) if needed.

        iptables -A INPUT -p tcp ! -s $IP --dport $PORT -j DROP
        /tftpboot/iptables_rule script sets iptables rule on the given node.
        """
        tftp_root = var['tftp_root']
        rule_path = tftp_root + "/iptables_rule"
        if user_data is not None:
            open_ip = base64.b64decode(user_data)
            utils.execute(rule_path, node_ip, open_ip)

    def activate_node(self, var, context, node, instance):
        network_info = var['network_info']
        for (_, mapping) in network_info:
            ip_address = mapping['ips'][0]['ip']
        node_ip = node['pm_address']
        mac_address = node['prov_mac_address']
        user_data = instance['user_data']
        LOG.debug(_("node_ip=%(node_ip)s mac=%(mac_address)s "
                    "ip_address=%(ip_address)s ud=%(user_data)s"),
                  locals())
        try:
            self._network_set(node_ip, mac_address, ip_address)
            self._ssh_set(node_ip)
            self._iptables_set(var, node_ip, user_data)
        except Exception as ex:
            self.deactivate_bootloader(var, context, node, instance)
            raise exception.NovaException(_("Node is unknown error state."))

    def deactivate_node(self, var, context, node, instance):
        pass

    def get_console_output(self, node, instance):
        """
        Gets console output of the given node.
        """
        var = self.define_vars(instance, None, None)
        console_log = os.path.join(CONF.instances_path, instance['name'],
                                   'console.log')
        tftp_root = var['tftp_root']
        node_ip = node['pm_address']
        log_path = tftp_root + "/log_" + str(node['id'])
        kmsg_cmd = (CONF.tile_monitor +
                    " --resume --net " + node_ip +
                    " -- dmesg > " + log_path)
        subprocess.Popen(kmsg_cmd, shell=True)
        time.sleep(CONF.tile_service_wait)
        utils.execute('cp', log_path, console_log)
