import os
import datetime

DB_PATH = os.getenv('DB_PATH', '/opt/pxewatch/pxe.db')
PRESEED_PATH = os.getenv('PRESEED_PATH', '/var/www/html/debian12/preseed.cfg')
DNSMASQ_PATH = '/etc/dnsmasq.conf'
BOOT_IPXE_PATH = '/srv/tftp/boot.ipxe'
AUTOEXEC_IPXE_PATH = '/srv/tftp/autoexec.ipxe'
LOGS_DIR = os.getenv('LOGS_DIR', '/var/log/installer')
ONLINE_TIMEOUT = int(os.getenv('ONLINE_TIMEOUT', 300))
LOCAL_OFFSET = datetime.timedelta(hours=int(os.getenv('LOCAL_OFFSET', 3)))
ANSIBLE_PLAYBOOK = '/root/ansible/playbook.yml'
ANSIBLE_INVENTORY = '/root/ansible/inventory.ini'
ANSIBLE_FILES_DIR = '/root/ansible/files'
ANSIBLE_TEMPLATES_DIR = '/root/ansible/templates'
