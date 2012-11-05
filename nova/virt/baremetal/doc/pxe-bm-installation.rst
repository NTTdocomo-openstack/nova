
Packages
========

* This procedure is for Ubuntu 12.04 x86_64. Reading 'pxe-bm-instance-creation.rst' may make this document easy to understand.

* dnsmasq (PXE server for baremetal hosts)
* syslinux (bootloader for PXE)
* ipmitool (operate IPMI)
* qemu-kvm (only for qemu-img)
* open-iscsi (connect to iSCSI target at berametal hosts)
* busybox (used in deployment ramdisk)
* tgt (used in deployment ramdisk)

Example::

	$ sudo apt-get install dnsmasq syslinux ipmitool qemu-kvm open-iscsi
	$ sudo apt-get install busybox tgt


Ramdisk for Deployment
======================

To create a deployment ramdisk, use 'baremetal-mkinitrd.sh' in [baremetal-initrd-builder](https://github.com/NTTdocomo-openstack/baremetal-initrd-builder)::

	$ cd baremetal-initrd-builder
	$ ./baremetal-mkinitrd.sh <ramdisk output path> <kernel version>

Modules in /lib/<kernel version>/modules are used to create ramdisk.
You can specify a 'generic' kernel installed to the working host.

Example::

	$ ./baremetal-mkinitrd.sh /tmp/deploy-ramdisk.img 3.2.0-32-generic
	working in /tmp/baremetal-mkinitrd.9AciX98N
	368017 blocks


Register the kernel and the ramdisk to Glance.

Example::

	$ glance image-create --name="baremetal deployment ramdisk" --public --container-format=ari --disk-format=ari < /tmp/deploy-ramdisk.img
	+------------------+--------------------------------------+
	| Property         | Value                                |
	+------------------+--------------------------------------+
	| checksum         | cbe12af4f684529ce4f16c82347b6b78     |
	| container_format | ari                                  |
	| created_at       | 2012-11-01T03:27:29                  |
	| deleted          | False                                |
	| deleted_at       | None                                 |
	| disk_format      | ari                                  |
	| id               | 97b93eaa-1841-4b1a-829b-3b2919c6aa77 |
	| is_public        | True                                 |
	| min_disk         | 0                                    |
	| min_ram          | 0                                    |
	| name             | baremetal deployment ramdisk         |
	| owner            | e6b9a92039d6440a9c22a3e6659d750d     |
	| protected        | False                                |
	| size             | 67323792                             |
	| status           | active                               |
	| updated_at       | 2012-11-01T03:27:30                  |
	+------------------+--------------------------------------+

	(You may have to make the kernel readable)
	$ sudo chmod a+r /boot/vmlinuz-3.2.0-32-generic
	$ glance image-create --name="baremetal deployment kernel" --public --container-format=aki --disk-format=aki < /boot/vmlinuz-3.2.0-32-generic
	+------------------+--------------------------------------+
	| Property         | Value                                |
	+------------------+--------------------------------------+
	| checksum         | 32168a6c0222dc3543816667abac4d42     |
	| container_format | aki                                  |
	| created_at       | 2012-11-01T03:29:12                  |
	| deleted          | False                                |
	| deleted_at       | None                                 |
	| disk_format      | aki                                  |
	| id               | cabedc5b-4efa-413f-82e2-bfca7c1f1097 |
	| is_public        | True                                 |
	| min_disk         | 0                                    |
	| min_ram          | 0                                    |
	| name             | baremetal deployment kernel          |
	| owner            | e6b9a92039d6440a9c22a3e6659d750d     |
	| protected        | False                                |
	| size             | 4966768                              |
	| status           | active                               |
	| updated_at       | 2012-11-01T03:29:13                  |
	+------------------+--------------------------------------+


ShellInABox
===========
Baremetal nova-compute uses [ShellInABox](http://code.google.com/p/shellinabox/) so that users can access baremetal host's console through web browsers.

Build from source and install::

	$ sudo apt-get install gcc make
	$ tar xzf shellinabox-2.14.tar.gz
	$ cd shellinabox-2.14
	$ ./configure
	$ sudo make install


PXE Boot Server
===============

Prepare TFTP root directory::

	$ sudo mkdir /tftpboot
	$ sudo cp /usr/lib/syslinux/pxelinux.0 /tftpboot/
	$ sudo mkdir /tftpboot/pxelinux.cfg

Start dnsmasq.
Example: start dnsmasq on eth1 with PXE and TFTP enabled::

	$ sudo dnsmasq --conf-file= --port=0 --enable-tftp --tftp-root=/tftpboot --dhcp-boot=pxelinux.0 --bind-interfaces --pid-file=/dnsmasq.pid --interface=eth1 --dhcp-range=192.168.175.100,192.168.175.254

	(You may need to stop and disable dnsmasq)
	$ sudo /etc/init.d/dnsmasq stop
	$ sudo sudo update-rc.d dnsmasq disable


Nova Directories
================

::

	$ sudo mkdir /var/lib/nova/baremetal
	$ sudo mkdir /var/lib/nova/baremetal/console
	$ sudo mkdir /var/lib/nova/baremetal/dnsmasq


Nova Flags
==========

Set these flags in nova.conf::

	# baremetal database connection
	# (The database will be created in the next section)
	baremetal_sql_connection = mysql://nova_bm:password@127.0.0.1/nova_bm

	# baremetal compute driver
	compute_driver = nova.virt.baremetal.driver.BareMetalDriver
	baremetal_driver = nova.virt.baremetal.pxe.PXE
	power_manager = nova.virt.baremetal.ipmi.Ipmi

	# instance_type_extra_specs this baremetal compute
	instance_type_extra_specs = cpu_arch:x86_64

	# TFTP root
	baremetal_tftp_root = /tftpboot

	# path to shellinaboxd
	baremetal_term = /usr/local/bin/shellinaboxd

	# deployment kernel & ramdisk image id
	baremetal_deploy_kernel = d76012fc-4055-485c-a978-f748679b89a9
	baremetal_deploy_ramdisk = e99775cb-f78d-401e-9d14-acd86e2f36e3

	# baremetal scheduler host manager
	scheduler_host_manager = nova.scheduler.baremetal_host_manager.BaremetalHostManager


Deplyment Kernel/RAMDisk per Image
----------------------------------

You can also specify a deploymant kernel/ramdisk by Glance's properties;
deploy_kernel_id and deploy_ramdisk_id. These properties take precidence over ones in nova.conf.

Example: set the properties to an image (29b99aad-99b7-4e58-bd55-7640eb8ea9ae)::

	$ glance image-update --property deploy_kernel_id=d76012fc-4055-485c-a978-f748679b89a9 --property deploy_ramdisk_id=e99775cb-f78d-401e-9d14-acd86e2f36e3 29b99aad-99b7-4e58-bd55-7640eb8ea9ae

Baremetal Database
==================

Create the baremetal database. Grant all provileges to the user specified by the 'baremetal_sql_connection' flag.
Example::

	$ mysql -p
	mysql> create database nova_bm;
	mysql> grant all privileges on nova_bm.* to 'nova_bm'@'%' identified by 'password';
	mysql> exit

Create tables::

	$ nova-baremetal-manage db sync


Create Baremetal Instance Type
==============================

First, create an instance type in the normal way.

Example::

	$ nova-manage instance_type create --name=bm.small --cpu=2 --memory=4096 --root_gb=10 --ephemeral_gb=20 --swap=1024 --rxtx_factor=1

Next, set baremetal extra_spec to the instance type::

	$ nova-manage instance_type set_key --name=bm.small --key cpu_arch --value 'x86_64'


Start Processes
===============

::

	$ nova-baremetal-deploy-heplper &
	$ nova-scheduler &
	$ nova-compute &


Register Baremetal Node and NIC
===============================

First, register a baremetal node. In this step, one of the NICs must be specified as a PXE NIC.
Ensure the NIC is PXE-enabled and the NIC is selected as a primary boot device in BIOS.

Next, register all the NICs except the PXE NIC specified in the first step.

To register a baremetal node, use 'nova-baremetal-manage node create'.
It takes the parameters listed below.

* --host: baremetal nova-compute's hostname
* --cpus: number of CPU cores
* --memory_mb: memory size in MegaBytes
* --local_gb: local disk size in GigaBytes
* --pm_address: IPMI address
* --pm_user: IPMI username
* --pm_password: IPMI password
* --prov_mac_address: PXE NIC's MAC address
* --terminal_port: TCP port for ShellInABox. Each node must use unique TCP port. If you do not need console access, use 0.

Example::

	$ nova-baremetal-manage node create --host=bm1 --cpus=4 --memory_mb=6144 --local_gb=64 --pm_address=172.27.2.116 --pm_user=test --pm_password=password --prov_mac_address=98:4b:e1:11:22:33 --terminal_port=8000

To verify the node registration, run 'nova-baremetal-manage node list'::

	$ nova-baremetal-manage node list
	ID        SERVICE_HOST  INSTANCE_ID   CPUS    Memory    Disk      PM_Address        PM_User           TERMINAL_PORT  PROV_MAC            PROV_VLAN
	1         bm1           None          4       6144      64        172.27.2.116      test              8000   98:4b:e1:11:22:33   None

To register a NIC, use 'nova-baremetal-manage interface create'.
It takes the parameters listed below.

* --node_id: ID of the baremetal node owns this NIC (the first column of 'nova-baremetal-manage node list')
* --mac_address: this NIC's MAC address in the form of xx:xx:xx:xx:xx:xx
* --datapath_id: datapath ID of OpenFlow switch this NIC is connected to
* --port_no: OpenFlow port number this NIC is connected to

(--datapath_id and --port_no are used for network isolation. It is OK to put 0, if you do not have OpenFlow switch.)

Example::

	$ nova-baremetal-manage interface create --node_id=1 --mac_address=98:4b:e1:11:22:34 --datapath_id=0x123abc --port_no=24

To verify the NIC registration, run 'nova-baremetal-manage interface list'::

	$ nova-baremetal-manage interface list
	ID        BM_NODE_ID        MAC_ADDRESS         DATAPATH_ID       PORT_NO
	1         1                 98:4b:e1:11:22:34   0x123abc          24


Run Instance
============

Run instance using the baremetal instance type.
Make sure to use kernel, ramdisk and image that support baremetal hardware (i.e contain drivers for baremetal hardware ).

Only partition images are currently supported. See 'How to create an image' section.

Example::

	euca-run-instances -t bm.small --kernel aki-AAA --ramdisk ari-BBB ami-CCC


How to create an image:
-----------------------

Example: create a partition image from ubuntu cloud images' Precise tarball::

	$ wget http://cloud-images.ubuntu.com/precise/current/precise-server-cloudimg-amd64-root.tar.gz
	$ dd if=/dev/zero of=precise.img bs=1M count=0 seek=1024
	$ mkfs -F -t ext4 precise.img
	$ sudo mount -o loop precise.img /mnt/
	$ sudo tar -C /mnt -xzf ~/precise-server-cloudimg-amd64-root.tar.gz
	$ sudo mv /mnt/etc/resolv.conf /mnt/etc/resolv.conf_orig
	$ sudo cp /etc/resolv.conf /mnt/etc/resolv.conf
	$ sudo chroot /mnt apt-get install linux-image-3.2.0-32-generic vlan open-iscsi
	$ sudo mv /mnt/etc/resolv.conf_orig /mnt/etc/resolv.conf
	$ sudo umount /mnt
