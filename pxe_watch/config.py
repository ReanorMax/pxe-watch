import os
import datetime

# Paths and settings
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
ANSIBLE_FILES_DIR = '/home/ansible-offline/files'
ANSIBLE_TEMPLATES_DIR = '/root/ansible/templates'

# SSH config
SSH_PASSWORD = os.getenv('SSH_PASSWORD', 'Q1w2a3s40007')
SSH_USER = os.getenv('SSH_USER', 'root')
SSH_OPTIONS = '-o StrictHostKeyChecking=no'

# Semaphore API
SEMAPHORE_API = 'http://10.19.1.90:3000/api'
SEMAPHORE_TOKEN = 'pkoqhsremgn9s_4d1qdrzf9lgxzmn8e9nwtjjillvss='
SEMAPHORE_PROJECT_ID = 1
SEMAPHORE_TEMPLATE_ID = 1
ANSIBLE_SERVICE_NAME = 'ansible-api.service'
