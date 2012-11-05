# vim: tabstop=4 shiftwidth=4 softtabstop=4
# coding=utf-8

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
Class for IPMI power manager.
"""

import os
import stat
import tempfile
import time

from nova import flags
from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova import utils
from nova.virt.baremetal import baremetal_states
from nova.virt.baremetal import utils as bm_utils
from nova.virt.libvirt import utils as libvirt_utils

opts = [
    cfg.StrOpt('baremetal_term',
               default='shellinaboxd',
               help='path to baremetal terminal program'),
    cfg.StrOpt('baremetal_term_cert_dir',
               default=None,
               help='path to baremetal terminal SSL cert(PEM)'),
    cfg.StrOpt('baremetal_term_pid_dir',
               default='$state_path/baremetal/console',
               help='path to directory stores pidfiles of baremetal_term'),
    cfg.IntOpt('baremetal_ipmi_power_retry',
               default=3,
               help='maximal number of retries for IPMI operations'),
    cfg.IntOpt('baremetal_ipmi_power_wait',
               default=5,
               help='wait time in seconds until check the result '
                    'after IPMI power operations'),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(opts)

LOG = logging.getLogger(__name__)


def _make_password_file(password):
    fd, path = tempfile.mkstemp()
    os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w") as f:
        f.write(password)
    return path


def _console_pidfile(node_id):
    name = "%s.pid" % node_id
    path = os.path.join(FLAGS.baremetal_term_pid_dir, name)
    return path


def _console_pid(node_id):
    pidfile = _console_pidfile(node_id)
    if os.path.exists(pidfile):
        pidstr = libvirt_utils.load_file(pidfile)
        try:
            return int(pidstr)
        except ValueError:
            pass
        LOG.warn("pidfile %s does not contain any pid", pidfile)
    return None


def _stop_console(node_id):
    console_pid = _console_pid(node_id)
    if console_pid:
        # Allow exitcode 99 (RC_UNAUTHORIZED)
        utils.execute('kill', '-TERM', str(console_pid),
                      run_as_root=True,
                      check_exit_code=[0, 99])
    bm_utils.unlink_without_raise(_console_pidfile(node_id))


class IpmiError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.msg = message

    def __str__(self):
        return "%s: %s" % (self.status, self.msg)


class Ipmi(object):

    def __init__(self, node):
        self._node_id = node['id']
        self._address = node['pm_address']
        self._user = node['pm_user']
        self._password = node['pm_password']
        self._interface = "lanplus"
        self._terminal_port = node['terminal_port']
        if self._address == None:
            raise IpmiError(-1, "address is None")
        if self._user == None:
            raise IpmiError(-1, "user is None")
        if self._password == None:
            raise IpmiError(-1, "password is None")

    def _exec_ipmitool(self, command):
        args = []
        args.append("ipmitool")
        args.append("-I")
        args.append(self._interface)
        args.append("-H")
        args.append(self._address)
        args.append("-U")
        args.append(self._user)
        args.append("-f")
        pwfile = _make_password_file(self._password)
        try:
            args.append(pwfile)
            args.extend(command.split(" "))
            out, err = utils.execute(*args, attempts=3)
        finally:
            bm_utils.unlink_without_raise(pwfile)
        LOG.debug("out: %s", out)
        LOG.debug("err: %s", err)
        return out, err

    def _power(self, state):
        count = 0
        while not self._is_power(state):
            count += 1
            if count > FLAGS.baremetal_ipmi_power_retry:
                return baremetal_states.ERROR
            try:
                self._exec_ipmitool("power %s" % state)
            except Exception:
                LOG.exception("_power(%s) failed" % state)
            time.sleep(FLAGS.baremetal_ipmi_power_wait)
        if state == "on":
            return baremetal_states.ACTIVE
        else:
            return baremetal_states.DELETED

    def _is_power(self, state):
        out_err = self._exec_ipmitool("power status")
        return out_err[0] == ("Chassis Power is %s\n" % state)

    def activate_node(self):
        self._power("off")
        state = self._power("on")
        return state

    def reboot_node(self):
        self._power("off")
        state = self._power("on")
        return state

    def deactivate_node(self):
        state = self._power("off")
        return state

    def is_power_on(self):
        return self._is_power("on")

    def start_console(self):
        if not self._terminal_port:
            return
        args = []
        args.append(FLAGS.baremetal_term)
        if FLAGS.baremetal_term_cert_dir:
            args.append("-c")
            args.append(FLAGS.baremetal_term_cert_dir)
        else:
            args.append("-t")
        args.append("-p")
        args.append(str(self._terminal_port))
        args.append("--background=%s" % _console_pidfile(self._node_id))
        args.append("-s")

        pwfile = _make_password_file(self._password)

        ipmi_args = "/:%(uid)s:%(gid)s:HOME:ipmitool -H %(address)s" \
                    " -I lanplus -U %(user)s -f %(pwfile)s sol activate" \
                    % {'uid': os.getuid(),
                       'gid': os.getgid(),
                       'address': self._address,
                       'user': self._user,
                       'pwfile': pwfile,
                       }

        args.append(ipmi_args)
        # Run shellinaboxd without pipes. Otherwise utils.execute() waits
        # infinitely since shellinaboxd does not close passed fds.
        x = ["'" + arg.replace("'", "'\\''") + "'" for arg in args]
        x.append('</dev/null')
        x.append('>/dev/null')
        x.append('2>&1')
        utils.execute(' '.join(x), shell=True)

    def stop_console(self):
        _stop_console(self._node_id)
