from datetime import timedelta
import os
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv('DB_PATH', '/opt/pxewatch/pxe.db')
PRESEED_DIR = os.getenv('PRESEED_DIR', '/var/www/html/debian12/preseeds')
PRESEED_PATH = os.getenv('PRESEED_PATH', '/var/www/html/debian12/preseed.cfg')
DNSMASQ_PATH = os.getenv('DNSMASQ_PATH', '/etc/dnsmasq.conf')
BOOT_IPXE_PATH = os.getenv('BOOT_IPXE_PATH', '/srv/tftp/boot.ipxe')
AUTOEXEC_IPXE_PATH = os.getenv('AUTOEXEC_IPXE_PATH', '/srv/tftp/autoexec.ipxe')
LOGS_DIR = os.getenv('LOGS_DIR', '/var/log/installer')
ONLINE_TIMEOUT = int(os.getenv('ONLINE_TIMEOUT', 300))
LOCAL_OFFSET = timedelta(hours=int(os.getenv('LOCAL_OFFSET', 3)))
ANSIBLE_PLAYBOOK = os.getenv('ANSIBLE_PLAYBOOK', '/root/ansible/playbook.yml')
ANSIBLE_INVENTORY = os.getenv('ANSIBLE_INVENTORY', '/root/ansible/inventory.ini')
ANSIBLE_FILES_DIR = os.getenv('ANSIBLE_FILES_DIR', '/home/ansible-offline/files')
ANSIBLE_TEMPLATES_DIR = os.getenv('ANSIBLE_TEMPLATES_DIR', '/root/ansible/templates')
SSH_PASSWORD = os.getenv('SSH_PASSWORD', '')
SSH_USER = os.getenv('SSH_USER', 'root')
SSH_OPTIONS = os.getenv(
    'SSH_OPTIONS',
    '-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null'
)
INSTALL_STATUS_PATH = os.getenv('INSTALL_STATUS_PATH', '/var/log/install_status.json')
