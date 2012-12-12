# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
Class for PXE bare-metal nodes.
"""

import os
import shutil

from nova.compute import instance_types
from nova import exception
from nova.network import linux_net
from nova.openstack.common import cfg
from nova.openstack.common import fileutils
from nova.openstack.common import log as logging
from nova import utils
from nova.virt.baremetal import base
from nova.virt.baremetal import db as bmdb
from nova.virt.baremetal import utils as bm_utils
from nova.virt.baremetal import vlan
from nova.virt.disk import api as disk
from nova.virt.libvirt import utils as libvirt_utils


LOG = logging.getLogger(__name__)

pxe_opts = [
    cfg.BoolOpt('baremetal_use_unsafe_vlan',
                default=False,
                help='use baremetal node\'s vconfig for network isolation'),
    cfg.BoolOpt('baremetal_pxe_vlan_per_host',
                default=False),
    cfg.StrOpt('baremetal_pxe_parent_interface',
               default='eth0'),
    cfg.StrOpt('baremetal_pxelinux_path',
               default='/usr/lib/syslinux/pxelinux.0',
               help='path to pxelinux.0'),
    cfg.StrOpt('baremetal_dnsmasq_pid_dir',
               default='$state_path/baremetal/dnsmasq',
               help='path to directory stores pidfiles of dnsmasq'),
    cfg.StrOpt('baremetal_dnsmasq_lease_dir',
               default='$state_path/baremetal/dnsmasq',
               help='path to directory stores leasefiles of dnsmasq'),
    cfg.StrOpt('baremetal_deploy_kernel',
               help='kernel image ID used in deployment phase'),
    cfg.StrOpt('baremetal_deploy_ramdisk',
               help='ramdisk image ID used in deployment phase'),
    cfg.BoolOpt('baremetal_pxe_append_iscsi_portal',
                default=True,
                help='append "bm_iscsi_porttal=<portal_address>" '
                     'to instances\' /proc/cmdline'),
    cfg.StrOpt('baremetal_pxe_append_params',
               help='additional append parameters for baremetal pxe'),
            ]

CONF = cfg.CONF
CONF.register_opts(pxe_opts)


def get_baremetal_nodes():
    return PXE()


Template = None


def _late_load_cheetah():
    global Template
    if Template is None:
        t = __import__('Cheetah.Template', globals(), locals(),
                       ['Template'], -1)
        Template = t.Template


def _dnsmasq_pid_path(pxe_interface):
    name = 'dnsmasq-%s.pid' % pxe_interface
    path = os.path.join(CONF.baremetal_dnsmasq_pid_dir, name)
    return path


def _dnsmasq_lease_path(pxe_interface):
    name = 'dnsmasq-%s.lease' % pxe_interface
    path = os.path.join(CONF.baremetal_dnsmasq_lease_dir, name)
    return path


def _dnsmasq_pid(pxe_interface):
    pidfile = _dnsmasq_pid_path(pxe_interface)
    if os.path.exists(pidfile):
        with open(pidfile, 'r') as f:
            return int(f.read())
    return None


def _random_alnum(count):
    import random
    import string
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choice(chars) for _ in range(count))


def _start_dnsmasq(interface, tftp_root, client_address, pid_path, lease_path):
    utils.execute('dnsmasq',
                  '--conf-file=',
                  '--pid-file=%s' % pid_path,
                  '--dhcp-leasefile=%s' % lease_path,
                  '--port=0',
                  '--bind-interfaces',
                  '--interface=%s' % interface,
                  '--enable-tftp',
                  '--tftp-root=%s' % tftp_root,
                  '--dhcp-boot=pxelinux.0',
                  '--dhcp-range=%s,%s' % (client_address, client_address),
                  run_as_root=True)


def _build_pxe_config(deployment_id, deployment_key, deployment_iscsi_iqn,
                      deployment_aki_path, deployment_ari_path,
                      aki_path, ari_path,
                      iscsi_portal):
    # nova-baremetal-deploy-helper will change 'default deploy'
    # to 'default boot' after the image deployment is complete
    pxeconf = "default deploy\n"
    pxeconf += "\n"

    pxeconf += "label deploy\n"
    pxeconf += "kernel %s\n" % deployment_aki_path
    pxeconf += "append"
    pxeconf += " initrd=%s" % deployment_ari_path
    pxeconf += " selinux=0"
    pxeconf += " disk=cciss/c0d0,sda,hda,vda"
    pxeconf += " iscsi_target_iqn=%s" % deployment_iscsi_iqn
    pxeconf += " deployment_id=%s" % deployment_id
    pxeconf += " deployment_key=%s" % deployment_key
    if CONF.baremetal_pxe_append_params:
        pxeconf += " %s" % CONF.baremetal_pxe_append_params
    pxeconf += "\n"
    pxeconf += "ipappend 3\n"
    pxeconf += "\n"

    pxeconf += "label boot\n"
    pxeconf += "kernel %s\n" % aki_path
    pxeconf += "append"
    pxeconf += " initrd=%s" % ari_path
    # nova-baremetal-deploy-helper will set ${ROOT} to proper UUID
    pxeconf += " root=${ROOT} ro"
    if iscsi_portal:
        pxeconf += ' bm_iscsi_portal=%s' % iscsi_portal
    if CONF.baremetal_pxe_append_params:
        pxeconf += " %s" % CONF.baremetal_pxe_append_params
    pxeconf += "\n"
    pxeconf += "\n"
    return pxeconf


def _start_per_host_pxe_server(tftp_root, vlan_id,
                               server_address, client_address):
    parent_interface = CONF.baremetal_pxe_parent_interface

    pxe_interface = vlan.ensure_vlan(vlan_id, parent_interface)

    chain = 'bm-%s' % pxe_interface
    iptables = linux_net.iptables_manager
    f = iptables.ipv4['filter']
    f.add_chain(chain)
    f.add_rule('INPUT', '-i %s -j $%s' % (pxe_interface, chain))
    f.add_rule(chain, '--proto udp --sport=68 --dport=67 -j ACCEPT')
    f.add_rule(chain, '-s %s -j ACCEPT' % client_address)
    f.add_rule(chain, '-j DROP')
    iptables.apply()

    utils.execute('ip', 'address',
                  'add', server_address + '/24',
                  'dev', pxe_interface,
                  run_as_root=True)
    utils.execute('ip', 'route', 'add',
                  client_address, 'scope', 'host', 'dev', pxe_interface,
                  run_as_root=True)

    shutil.copyfile(CONF.baremetal_pxelinux_path,
                    os.path.join(tftp_root, 'pxelinux.0'))
    fileutils.ensure_tree(os.path.join(tftp_root, 'pxelinux.cfg'))

    _start_dnsmasq(interface=pxe_interface,
                   tftp_root=tftp_root,
                   client_address=client_address,
                   pid_path=_dnsmasq_pid_path(pxe_interface),
                   lease_path=_dnsmasq_lease_path(pxe_interface))


def _stop_per_host_pxe_server(tftp_root, vlan_id):
    pxe_interface = 'vlan%d' % vlan_id

    dnsmasq_pid = _dnsmasq_pid(pxe_interface)
    if dnsmasq_pid:
        utils.execute('kill', '-TERM', str(dnsmasq_pid), run_as_root=True)
    bm_utils.unlink_without_raise(_dnsmasq_pid_path(pxe_interface))
    bm_utils.unlink_without_raise(_dnsmasq_lease_path(pxe_interface))

    vlan.ensure_no_vlan(vlan_id, CONF.baremetal_pxe_parent_interface)

    shutil.rmtree(os.path.join(tftp_root, 'pxelinux.cfg'), ignore_errors=True)

    chain = 'bm-%s' % pxe_interface
    iptables = linux_net.iptables_manager
    iptables.ipv4['filter'].remove_chain(chain)
    iptables.apply()


class PXE(base.NodeDriver):

    def define_vars(self, instance, network_info, block_device_info):
        var = {}
        var['image_root'] = os.path.join(CONF.instances_path,
                                         instance['name'])
        if CONF.baremetal_pxe_vlan_per_host:
            var['tftp_root'] = os.path.join(CONF.baremetal_tftp_root,
                                            str(instance['uuid']))
        else:
            var['tftp_root'] = CONF.baremetal_tftp_root
        var['network_info'] = network_info
        var['block_device_info'] = block_device_info
        return var

    def _collect_mac_addresses(self, context, node):
        macs = [nic['address']
                for nic in bmdb.bm_interface_get_all_by_bm_node_id(
                        context, node['id'])]
        return macs

    def _generate_persistent_net_rules(self, macs):
        rules = ''
        for (i, mac) in enumerate(macs):
            rules += 'SUBSYSTEM=="net", ACTION=="add", DRIVERS=="?*", ' \
                     'ATTR{address}=="%(mac)s", ATTR{dev_id}=="0x0", ' \
                     'ATTR{type}=="1", KERNEL=="eth*", NAME="%(name)s"\n' \
                     % {'mac': mac.lower(),
                        'name': 'eth%d' % i,
                        }
        return rules

    def _generate_network_config(self, network_info, bootif_name):
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
            if (CONF.baremetal_use_unsafe_vlan
                    and mapping['should_create_vlan']
                    and network_ref.get('vlan')):
                name = 'eth%d.%d' % (ifc_num, network_ref.get('vlan'))
            net_info = {'name': name,
                        'address': address,
                        'netmask': netmask,
                        'gateway': mapping['gateway'],
                        'broadcast': mapping['broadcast'],
                        'dns': ' '.join(mapping['dns']),
                        'address_v6': address_v6,
                        'gateway_v6': gateway_v6,
                        'netmask_v6': netmask_v6,
                        'hwaddress': mapping['mac'],
                        }
            nets.append(net_info)

        ifc_template = open(CONF.baremetal_injected_network_template).read()
        _late_load_cheetah()
        net = str(Template(ifc_template,
                           searchList=[{'interfaces': nets,
                                        'use_ipv6': CONF.use_ipv6,
                                        }]))
        net += '\n'
        net += 'auto %s\n' % bootif_name
        net += 'iface %s inet dhcp\n' % bootif_name
        return net

    def _inject_to_image(self, context, target, node, inst, network_info,
                         injected_files=None, admin_password=None):
        if injected_files is None:
            injected_files = []
        # For now, we assume that if we're not using a kernel, we're using a
        # partitioned disk image where the target partition is the first
        # partition
        target_partition = None
        if not inst['kernel_id']:
            target_partition = "1"

        # udev renames the nics so that they are in the same order as in BMDB
        macs = self._collect_mac_addresses(context, node)
        bootif_name = "eth%d" % len(macs)
        macs.append(node['prov_mac_address'])
        rules = self._generate_persistent_net_rules(macs)
        injected_files.append(
                ('/etc/udev/rules.d/70-persistent-net.rules', rules))

        if inst['hostname']:
            injected_files.append(('/etc/hostname', inst['hostname']))

        net = self._generate_network_config(network_info, bootif_name)

        if inst['key_data']:
            key = str(inst['key_data'])
        else:
            key = None

        if not CONF.baremetal_inject_password:
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
        self._inject_to_image(context, image_path, node,
                              instance, network_info,
                              injected_files=injected_files,
                              admin_password=admin_password)
        var['image_path'] = image_path
        LOG.debug(_("fetching images all done"))

    def destroy_images(self, var, context, node, instance):
        image_root = var['image_root']
        shutil.rmtree(image_root, ignore_errors=True)

    def _pxe_cfg_name(self, node):
        name = "01-" + node['prov_mac_address'].replace(":", "-").lower()
        return name

    def _get_deploy_aki_id(self, image_meta):
        props = image_meta.get('properties', {})
        return props.get('deploy_kernel_id', CONF.baremetal_deploy_kernel)

    def _get_deploy_ari_id(self, image_meta):
        props = image_meta.get('properties', {})
        return props.get('deploy_ramdisk_id', CONF.baremetal_deploy_ramdisk)

    def _put_tftp_images(self, context, instance, image_meta, tftp_root):
        def _cache_image(image_id, target):
            LOG.debug(_("fetching id=%(image_id)s target=%(target)s"),
                      locals())
            bm_utils.cache_image(context=context,
                                 image_id=image_id,
                                 target=target,
                                 user_id=instance['user_id'],
                                 project_id=instance['project_id'])

        try:
            aki_id = str(instance['kernel_id'])
            ari_id = str(instance['ramdisk_id'])
        except KeyError as e:
            raise exception.NovaException(_('Can not activate baremetal '
                        'bootloader, %s is not defined') % e)
        deploy_aki_id = self._get_deploy_aki_id(image_meta)
        if not deploy_aki_id:
            raise exception.NovaException(_('Can not activate baremetal '
                        'bootloader, %s is not defined') % 'deploy_kernel_id')
        deploy_ari_id = self._get_deploy_ari_id(image_meta)
        if not deploy_ari_id:
            raise exception.NovaException(_('Can not activate baremetal '
                        'bootloader, %s is not defined') % 'deploy_ramdisk_id')

        images = [(deploy_aki_id, 'deploy_kernel'),
                  (deploy_ari_id, 'deploy_ramdisk'),
                  (aki_id, 'kernel'),
                  (ari_id, 'ramdisk'),
                  ]

        LOG.debug(_("Activating bootloader with images: %s") % images)
        fileutils.ensure_tree(tftp_root)
        if not CONF.baremetal_pxe_vlan_per_host:
            fileutils.ensure_tree(os.path.join(tftp_root, instance['uuid']))

        tftp_paths = []
        for image_id, tftp_path in images:
            if not CONF.baremetal_pxe_vlan_per_host:
                tftp_path = os.path.join(instance['uuid'], tftp_path)
            target = os.path.join(tftp_root, tftp_path)
            _cache_image(image_id, target)
            tftp_paths.append(tftp_path)
        return tftp_paths

    def _create_deployment(self, context, instance, image_path,
                           pxe_config_path):
        root_mb = instance['root_gb'] * 1024

        inst_type_id = instance['instance_type_id']
        inst_type = instance_types.get_instance_type(inst_type_id)
        swap_mb = inst_type['swap']
        # Always create a swap partition for simpler code paths in the
        # deployment side. Its up to the user to choose how big - use 1MB if
        # they don't choose anything at all.
        if swap_mb < 1:
            swap_mb = 1

        deployment_key = _random_alnum(32)
        deployment_id = bmdb.bm_deployment_create(context, deployment_key,
                                                  image_path, pxe_config_path,
                                                  root_mb, swap_mb)
        deployment = bmdb.bm_deployment_get(context, deployment_id)
        return deployment

    def activate_bootloader(self, var, context, node, instance, image_meta):
        tftp_root = var['tftp_root']
        image_path = var['image_path']

        tftp_paths = self._put_tftp_images(context, instance, image_meta,
                                           tftp_root)
        LOG.debug(_("tftp_paths for instance %(uuid)s: %(tftp_paths)s"),
                  {'uuid': instance['uuid'], 'tftp_paths': tftp_paths})

        pxe_config_dir = os.path.join(tftp_root, 'pxelinux.cfg')
        pxe_config_path = os.path.join(pxe_config_dir,
                                       self._pxe_cfg_name(node))

        deployment = self._create_deployment(context, instance, image_path,
                                             pxe_config_path)

        pxe_ip = None
        if CONF.baremetal_pxe_vlan_per_host:
            pxe_ip_id = bmdb.bm_pxe_ip_associate(context, node['id'])
            pxe_ip = bmdb.bm_pxe_ip_get(context, pxe_ip_id)

        deployment_iscsi_iqn = "iqn-%s" % instance['uuid']
        iscsi_portal = None
        if CONF.baremetal_pxe_append_iscsi_portal:
            if pxe_ip:
                iscsi_portal = pxe_ip['server_address']
        pxeconf = _build_pxe_config(deployment['id'],
                                    deployment['key'],
                                    deployment_iscsi_iqn,
                                    deployment_aki_path=tftp_paths[0],
                                    deployment_ari_path=tftp_paths[1],
                                    aki_path=tftp_paths[2],
                                    ari_path=tftp_paths[3],
                                    iscsi_portal=iscsi_portal)
        fileutils.ensure_tree(pxe_config_dir)
        libvirt_utils.write_to_file(pxe_config_path, pxeconf)

        if CONF.baremetal_pxe_vlan_per_host:
            _start_per_host_pxe_server(tftp_root,
                                       node['prov_vlan_id'],
                                       pxe_ip['server_address'],
                                       pxe_ip['address'])

    def deactivate_bootloader(self, var, context, node, instance):
        tftp_root = var['tftp_root']

        if CONF.baremetal_pxe_vlan_per_host:
            _stop_per_host_pxe_server(tftp_root, node['prov_vlan_id'])
            bmdb.bm_pxe_ip_disassociate(context, node['id'])
            tftp_image_dir = tftp_root
        else:
            tftp_image_dir = os.path.join(tftp_root, str(instance['uuid']))
        shutil.rmtree(tftp_image_dir, ignore_errors=True)

        pxe_config_path = os.path.join(tftp_root,
                                       "pxelinux.cfg",
                                       self._pxe_cfg_name(node))
        bm_utils.unlink_without_raise(pxe_config_path)

    def activate_node(self, var, context, node, instance):
        pass

    def deactivate_node(self, var, context, node, instance):
        pass

    def get_console_output(self, node, instance):
        raise NotImplementedError()
