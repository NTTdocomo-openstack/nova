# Copyright (c) 2013 NTT DOCOMO, INC.
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

"""The bare-metal admin extension."""

import webob

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import exception
from nova.openstack.common import log as logging
from nova.virt.baremetal import db

LOG = logging.getLogger(__name__)
authorize = extensions.extension_authorizer('compute', 'baremetal_nodes')

node_fields = ['id', 'cpus', 'local_gb', 'memory_mb', 'pm_address',
               'pm_user', 'prov_mac_address', 'prov_vlan_id',
               'service_host', 'terminal_port', 'instance_uuid',
               ]

interface_fields = ['id', 'address', 'datapath_id', 'port_no']


def _node_dict(node_ref):
    d = {}
    for f in node_fields:
        d[f] = node_ref.get(f)
    return d


def _interface_dict(interface_ref):
    d = {}
    for f in interface_fields:
        d[f] = interface_ref.get(f)
    return d


def _make_node_elem(elem):
    for f in node_fields:
        elem.set(f)


def _make_interface_elem(elem):
    for f in interface_fields:
        elem.set(f)


class NodeTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        node_elem = xmlutil.TemplateElement('node', selector='node')
        _make_node_elem(node_elem)
        ifs_elem = xmlutil.TemplateElement('interfaces')
        if_elem = xmlutil.SubTemplateElement(ifs_elem, 'interface',
                                             selector='interfaces')
        _make_interface_elem(if_elem)
        node_elem.append(ifs_elem)
        return xmlutil.MasterTemplate(node_elem, 1)


class NodesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('nodes')
        node_elem = xmlutil.SubTemplateElement(root, 'node', selector='nodes')
        _make_node_elem(node_elem)
        ifs_elem = xmlutil.TemplateElement('interfaces')
        if_elem = xmlutil.SubTemplateElement(ifs_elem, 'interface',
                                             selector='interfaces')
        _make_interface_elem(if_elem)
        node_elem.append(ifs_elem)
        return xmlutil.MasterTemplate(root, 1)


class InterfaceTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('interface', selector='interface')
        _make_interface_elem(root)
        return xmlutil.MasterTemplate(root, 1)


class BareMetalNodeController(object):
    """The Bare-Metal Node API controller for the OpenStack API."""
    def __init__(self):
        pass

    @wsgi.serializers(xml=NodesTemplate)
    def index(self, req):
        context = req.environ['nova.context']
        authorize(context)
        nodes_from_db = db.bm_node_get_all(context)
        nodes = []
        for node_from_db in nodes_from_db:
            try:
                ifs = db.bm_interface_get_all_by_bm_node_id(
                        context, node_from_db['id'])
            except exception.InstanceNotFound:
                ifs = []
            node = _node_dict(node_from_db)
            node['interfaces'] = [_interface_dict(i) for i in ifs]
            nodes.append(node)
        return {'nodes': nodes}

    @wsgi.serializers(xml=NodeTemplate)
    def show(self, req, id):
        context = req.environ['nova.context']
        authorize(context)
        try:
            node = db.bm_node_get(context, id)
        except exception.InstanceNotFound:
            raise webob.exc.HTTPNotFound
        try:
            ifs = db.bm_interface_get_all_by_bm_node_id(context, id)
        except exception.InstanceNotFound:
            ifs = []
        node = _node_dict(node)
        node['interfaces'] = [_interface_dict(i) for i in ifs]
        return {'node': node}

    @wsgi.serializers(xml=NodeTemplate)
    def create(self, req, body):
        context = req.environ['nova.context']
        authorize(context)
        node = db.bm_node_create(context, body['node'])
        node = _node_dict(node)
        node['interfaces'] = []
        return {'node': node}

    def delete(self, req, id):
        context = req.environ['nova.context']
        authorize(context)
        try:
            db.bm_node_destroy(context, id)
        except exception.InstanceNotFound:
            raise webob.exc.HTTPNotFound
        return webob.Response(status_int=202)

    @wsgi.serializers(xml=InterfaceTemplate)
    def action(self, req, id, body):
        context = req.environ['nova.context']

        try:
            db.bm_node_get(context, id)
        except exception.InstanceNotFound:
            raise webob.exc.HTTPNotFound

        _actions = {
            'add_interface': self._add_interface,
            'remove_interface': self._remove_interface,
        }
        for action, data in body.iteritems():
            try:
                return _actions[action](req, id, data)
            except KeyError:
                msg = _("BareMetalNodes does not have %s action") % action
                raise webob.exc.HTTPBadRequest(explanation=msg)

        raise webob.exc.HTTPBadRequest(explanation=_("Invalid request body"))

    def _add_interface(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context)
        address = body['address']
        datapath_id = body.get('datapath_id')
        port_no = body.get('port_no')
        if_id = db.bm_interface_create(context,
                                       bm_node_id=id,
                                       address=address,
                                       datapath_id=datapath_id,
                                       port_no=port_no)
        if_ref = db.bm_interface_get(context, if_id)
        return {'interface': _interface_dict(if_ref)}

    def _remove_interface(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context)
        if_id = body.get('id')
        address = body.get('address')
        if not if_id and not address:
            raise webob.exc.HTTPBadRequest(
                    explanation=_("Must specify id or address"))
        ifs = db.bm_interface_get_all_by_bm_node_id(context, id)
        for i in ifs:
            if if_id and if_id != i['id']:
                continue
            if address and address != i['address']:
                continue
            db.bm_interface_destroy(context, i['id'])
            return webob.Response(status_int=202)
        raise webob.exc.HTTPNotFound


class Baremetal_nodes(extensions.ExtensionDescriptor):
    """Admin-only bare-metal node administration"""

    name = "BareMetalNodes"
    alias = "os-baremetal-nodes"
    namespace = "http://docs.openstack.org/compute/ext/baremetal_nodes/api/v2"
    updated = "2013-01-04T00:00:00+00:00"

    def __init__(self, ext_mgr):
        ext_mgr.register(self)

    def get_resources(self):
        resources = []
        res = extensions.ResourceExtension('os-baremetal-nodes',
                BareMetalNodeController(),
                member_actions={"action": "POST", })
        resources.append(res)
        return resources
