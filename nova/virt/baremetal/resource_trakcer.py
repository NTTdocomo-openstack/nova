# vim: tabstop=4 shiftwidth=4 softtabstop=4
# coding=utf-8
#
# Copyright (c) 2012 NTT DOCOMO, INC
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
A resource tracker for bare-metal.
"""

from nova.compute import resource_tracker as base_rt


class BareMetalResourceTracker(base_rt.ResourceTracker):
    def apply_instance_to_resources(self, resources, instance, sign):
        """Update resources by instance and sign.
        This method is overridden to modify the way to consume resources.
        """
        ratio = 1 if sign > 0 else 0
        resources['memory_mb_used'] += ratio * resources['memory_mb']
        resources['local_gb_used'] += ratio * resources['local_gb']
