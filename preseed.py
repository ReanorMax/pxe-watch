from flask import Blueprint, render_template, request, send_file, jsonify
import io
import re
from datetime import datetime
import json
from pathlib import Path

preseed_bp = Blueprint('preseed', __name__, template_folder='templates')

TEMPLATES_FILE = Path('preseed_templates.json')
HISTORY_FILE = Path('preseed_history.json')

def load_templates():
    if not TEMPLATES_FILE.exists():
        return []
    try:
        with open(TEMPLATES_FILE) as f:
            return json.load(f).get('шаблоны', [])
    except Exception:
        return []

def save_templates(templates):
    with open(TEMPLATES_FILE, 'w') as f:
        json.dump({'шаблоны': templates}, f, indent=2)

def load_history():
    if not HISTORY_FILE.exists():
        return []
    try:
        with open(HISTORY_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return []

def save_to_history(data, preseed):
    history = load_history()
    history.append({
        'timestamp': datetime.now().isoformat(),
        'params': data,
        'preseed_preview': preseed[:500] + '...' if len(preseed) > 500 else preseed
    })
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history[-20:], f, indent=2)

@preseed_bp.route('/')
def index():
    return render_template('preseed/index.html')

@preseed_bp.route('/api/templates')
def api_templates():
    return jsonify([{'name': t['name']} for t in load_templates()])

@preseed_bp.route('/api/template/<name>')
def api_template(name):
    for template in load_templates():
        if template['name'] == name:
            return jsonify(template['data'])
    return "Шаблон не найден", 404

@preseed_bp.route('/api/save-template', methods=['POST'])
def api_save_template():
    try:
        data = request.get_json()
        if not data or 'name' not in data or 'data' not in data:
            return "Некорректные данные", 400
        templates = load_templates()
        if any(t['name'] == data['name'] for t in templates):
            return "Шаблон с таким именем уже существует", 400
        templates.append({'name': data['name'], 'data': data['data']})
        save_templates(templates)
        return "OK", 200
    except Exception as e:
        return f"Ошибка: {str(e)}", 500

@preseed_bp.route('/api/history')
def api_history():
    return jsonify(load_history())

@preseed_bp.route('/preview', methods=['POST'])
@preseed_bp.route('/generate', methods=['POST'])
def preview_or_generate():
    try:
        raid_level = request.form.get('raid_level', '1')
        disk_count = int(request.form['disk_count'])
        hot_spare = request.form.get('hot_spare') == 'on'
        min_disks = 1 if raid_level == '0' else 2
        if hot_spare and raid_level == '1':
            min_disks += 1
        if disk_count < min_disks:
            return (
                f"Ошибка: Для RAID-{raid_level}{' с hot spare' if hot_spare else ''} требуется минимум {min_disks} дисков",
                400,
            )
        partitions = {}
        for part in ['efi', 'boot', 'root', 'home', 'var', 'swap']:
            size = request.form[f'{part}_size'].strip()
            if not re.match(r'^\d+[kKmMgG]?$', size):
                return (
                    f"Ошибка: Некорректный размер для {part} ({size}). Примеры: 512, 1G, 2048M",
                    400,
                )
            if part == 'efi' and int(re.sub(r'[^\d]', '', size)) < 100:
                return "Ошибка: Размер EFI раздела должен быть не менее 100M", 400
            partitions[part] = size
        if len(request.form['root_password']) < 8:
            return "Ошибка: Пароль root должен быть не менее 8 символов", 400
        if request.form.get('mirror_mode') == 'custom':
            mirrors = []
            for i in range(1, 6):
                url = request.form.get(f'mirror_url_{i}', '').strip()
                if url:
                    mirrors.append(url)
            if not mirrors:
                return "Ошибка: Укажите хотя бы одно зеркало", 400
        if request.form.get('enable_ipxe') == 'on':
            ipxe_url = request.form.get('ipxe_url', '').strip()
            if not ipxe_url:
                return "Ошибка: Укажите URL сервера регистрации", 400
            if not ipxe_url.startswith(('http://', 'https://')):
                return "Ошибка: URL должен начинаться с http:// или https://", 400
            if (
                request.form.get('register_dhcp') != 'on'
                and request.form.get('register_disk') != 'on'
            ):
                return "Ошибка: Выберите хотя бы один этап регистрации", 400
        net_mode = request.form.get('net_mode', 'dhcp')
        if net_mode == 'static':
            required_fields = ['net_ip', 'net_netmask', 'net_gateway', 'net_dns']
            for field in required_fields:
                if not request.form.get(field):
                    return f"Ошибка: Требуется поле '{field}' для статической сети", 400
        data = {
            'disk_count': disk_count,
            'raid_level': raid_level,
            'hot_spare': hot_spare,
            'partitions': [partitions[p] for p in ['efi', 'boot', 'root', 'home', 'var', 'swap']],
            'hostname': request.form['hostname'],
            'root_password': request.form['root_password'],
            'username': request.form['username'],
            'user_password': request.form['user_password'],
            'mirror_host': request.form['mirror_host'],
            'mirror_mode': request.form.get('mirror_mode', 'default'),
            'timezone': request.form['timezone'],
            'locale': request.form['locale'],
            'net_mode': net_mode,
            'net_ip': request.form.get('net_ip', ''),
            'net_netmask': request.form.get('net_netmask', ''),
            'net_gateway': request.form.get('net_gateway', ''),
            'net_dns': request.form.get('net_dns', ''),
            'enable_ipxe': request.form.get('enable_ipxe', 'off'),
            'ipxe_url': request.form.get('ipxe_url', ''),
            'register_dhcp': request.form.get('register_dhcp', 'off'),
            'register_disk': request.form.get('register_disk', 'off'),
            'enable_ansible': request.form.get('enable_ansible', 'off'),
            'ansible_script': request.form.get('ansible_script', 'http://10.19.1.104:8081/repository/artifacts-local/other/config/ansible-register.sh'),
            'show_ip': request.form.get('show_ip', 'off'),
            'fix_hostname': request.form.get('fix_hostname', 'on'),
            'disable_video': request.form.get('disable_video', 'off'),
            'enable_font': request.form.get('enable_font', 'on'),
            'font_face': request.form.get('font_face', 'Terminus'),
            'font_size': request.form.get('font_size', '16x32'),
            'install_base_packages': request.form.get('install_base_packages', 'on'),
            'enable_root_ssh': request.form.get('enable_root_ssh', 'on'),
            'disable_sound': request.form.get('disable_sound', 'on'),
            'extended_registration': request.form.get('extended_registration', 'on'),
        }
        if data['mirror_mode'] == 'custom':
            data['mirrors'] = []
            for i in range(1, 6):
                url = request.form.get(f'mirror_url_{i}', '').strip()
                if url:
                    data['mirrors'].append(url)
        preseed = generate_preseed(data)
        if request.path.endswith('generate'):
            save_to_history(data, preseed)
            return send_file(
                io.BytesIO(preseed.encode('utf-8')),
                mimetype='text/plain',
                as_attachment=True,
                download_name=f"debian12-preseed-{data['hostname']}.cfg",
            )
        return preseed
    except ValueError:
        return "Ошибка: Некорректные числовые значения", 400
    except Exception as e:
        return f"Критическая ошибка: {str(e)}", 500

def generate_preseed(data):
    disks = [f"/dev/sd{chr(97 + i)}" for i in range(data['disk_count'])]
    disk_string = ' '.join(disks)

    def raid_paths(part_num):
        return '#'.join([f"{disk}{part_num}" for disk in disks])

    def convert_size(size, default_unit='M'):
        size = str(size).strip().upper()
        if size.endswith('G'):
            return str(int(float(size[:-1]) * 1024))
        elif size.endswith('M'):
            return size[:-1]
        elif size.endswith('K'):
            return str(int(size[:-1]) / 1024)
        return size

    efi_size = convert_size(data['partitions'][0], 'M')
    boot_size = convert_size(data['partitions'][1], 'M')
    root_size = convert_size(data['partitions'][2], 'M')
    home_size = convert_size(data['partitions'][3], 'M')
    var_size = convert_size(data['partitions'][4], 'M')
    swap_size = convert_size(data['partitions'][5], 'M')
    for size in [efi_size, boot_size, root_size, home_size, var_size, swap_size]:
        if int(size) <= 0:
            raise ValueError("Размер раздела должен быть положительным числом")

    raid_level = data['raid_level']
    spare_disks = 1 if data['hot_spare'] and raid_level == '1' else 0

    expert_recipe = f"""\
      multiraid :: \\
        {efi_size} {efi_size} {efi_size} fat32 \\
          $primary{{ }} \\
          $bootable{{ }} \\
          method{{ efi }} \\
          format{{ }} \\
        . \\
        {boot_size} {boot_size} {boot_size} raid \\
          $primary{{ }} \\
          method{{ raid }} \\
        . \\
        {root_size} {root_size} {root_size} raid \\
          $primary{{ }} \\
          method{{ raid }} \\
        . \\
        {home_size} {home_size} {home_size} raid \\
          $primary{{ }} \\
          method{{ raid }} \\
        . \\
        {var_size} {var_size} {var_size} raid \\
          $primary{{ }} \\
          method{{ raid }} \\
        . \\
        {swap_size} {swap_size} {swap_size} linux-swap \\
          method{{ swap }} \\
          format{{ }} \\
        .
    """

    raid_recipe = f"""\
      {raid_level} {data['disk_count']} {spare_disks} ext4 /boot {raid_paths('2')} \\
      . \\
      {raid_level} {data['disk_count']} {spare_disks} ext4 / {raid_paths('3')} \\
      . \\
      {raid_level} {data['disk_count']} {spare_disks} ext4 /home {raid_paths('4')} \\
      . \\
      {raid_level} {data['disk_count']} {spare_disks} ext4 /var {raid_paths('5')} \\
      .
    """

    preseed_lines = [
        "# =============================!===============================",
        "# Debian 12 (bookworm) — автоматическая установка",
        f"# UEFI + RAID-{raid_level} ({data['disk_count']}×SSD/HDD), EFI без RAID, /boot RAID-{raid_level}",
        f"# Сгенерировано: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "# ============================================================",
        ""
    ]

    if data.get('enable_ipxe') == 'on' and data.get('register_dhcp') == 'on':
        preseed_lines.extend([
            "",
            "### 🛰️  ЭТАП 1: РЕГИСТРАЦИЯ ПОСЛЕ DHCP",
            "### ============================================================",
            "",
        ])
        preseed_lines.extend([
            f"d-i preseed/early_command string \\",
            "  sh -c 'iface=$(ip route | awk \"/default/ {print $5; exit}\"); \\",
            "  mac=$(cat /sys/class/net/$iface/address); \\",
            "  ip_addr=$(ip -4 -o addr show $iface | awk \"{split($4,a,\"/\"); print a[1]}\"); \\",
            "  mkdir -p /var/log/installer; \\",
            "  exec > /var/log/installer/syslog.$mac 2>&1; \\",
            f"  wget -q --post-data \"mac=$mac&ip=$ip_addr&stage=dhcp\" \"{data['ipxe_url']}\" || true'",
        ])
    if data['net_mode'] == 'static':
        preseed_lines.extend([
            "",
            "### ============================================================",
            "### 🌐  СЕТЕВАЯ КОНФИГУРАЦИЯ (статическая)",
            "### ============================================================",
            "",
            "d-i netcfg/disable_autoconfig boolean true",
            "d-i netcfg/dhcp_timeout string 60",
            f"d-i netcfg/get_hostname string {data['hostname']}",
            "d-i netcfg/get_domain string local",
            "d-i netcfg/wireless_wep string",
            f"d-i netcfg/ipaddress string {data['net_ip']}",
            f"d-i netcfg/netmask string {data['net_netmask']}",
            f"d-i netcfg/gateway string {data['net_gateway']}",
            f"d-i netcfg/dns string {data['net_dns']}",
            "d-i netcfg/confirm_static boolean true",
            ""
        ])
    else:
        preseed_lines.extend([
            "",
            "### ============================================================",
            "### 🌐  СЕТЕВАЯ КОНФИГУРАЦИЯ (DHCP)",
            "### ============================================================",
            "",
            "d-i netcfg/choose_interface select auto",
            f"d-i netcfg/get_hostname string {data['hostname']}",
            "d-i netcfg/wireless_wep string",
            ""
        ])

    preseed_lines.extend([
        "",
        "### ============================================================",
        "### ⌨️  ОСНОВНЫЕ НАСТРОЙКИ (Locale, Keyboard, Installer)",
        "### ============================================================",
        "",
        f"d-i debian-installer/locale string {data['locale']}",
        "d-i console-setup/ask_detect boolean false",
        "d-i keyboard-configuration/xkb-keymap select us,ru",
        "d-i debian-installer/quiet boolean true",
        "d-i preseed/quiet boolean true",
        ""
    ])

    if data['mirror_mode'] == 'default':
        preseed_lines.extend([
            "",
            "### ============================================================",
            "### 📦  ЭТАП 2: ЗЕРКАЛА APT",
            "### ============================================================",
            "",
            "d-i mirror/country string manual",
            f"d-i mirror/http/hostname string {data['mirror_host']}",
            "d-i mirror/http/directory string /repository/debian-bookworm-proxy",
            "d-i mirror/http/proxy string",
            ""
        ])
    else:
        preseed_lines.extend([
            "",
            "### ============================================================",
            "### 📦  ЭТАП 2: КАСТОМНЫЕ ЗЕРКАЛА APT",
            "### ============================================================",
            "",
            "d-i apt-setup/use_mirror boolean false",
            "d-i apt-setup/services-select multiselect security, volatile",
            "d-i apt-setup/security_host string security.debian.org",
            ""
        ])

    preseed_lines.extend([
        "",
        "### ============================================================",
        f"### 💽  ЭТАП 3: РАЗМЕТКА ДИСКОВ (RAID-{raid_level})",
        "### ============================================================",
        "",
        f"d-i partman-auto/disk string {disk_string}",
        "d-i partman-auto/method string raid",
        "d-i partman-lvm/device_remove_lvm boolean true",
        "d-i partman-md/device_remove_md boolean true",
        "d-i partman-auto/expert_recipe string \\",
        expert_recipe.strip(),
        "",
        "d-i partman-auto-raid/recipe string \\",
        raid_recipe.strip(),
        ""
    ])

    preseed_lines.extend([
        "",
        "### ============================================================",
        "### 🧨  ЭТАП 4: ПОДТВЕРЖДЕНИЕ РАЗМЕТКИ",
        "### ============================================================",
        "",
        "d-i partman-partitioning/confirm_write_new_label boolean true",
        "d-i partman/choose_partition select finish",
        "d-i partman/confirm boolean true",
        "d-i partman/confirm_nooverwrite boolean true",
        "d-i partman-md/confirm boolean true",
        "d-i partman-md/confirm_nooverwrite boolean true",
        "",
        "### ============================================================",
        "### 👤  ЭТАП 5: УЧЁТНЫЕ ЗАПИСИ",
        "### ============================================================",
        "",
        f"d-i passwd/root-password password {data['root_password']}",
        f"d-i passwd/root-password-again password {data['root_password']}",
        f"d-i passwd/user-fullname string {data['username']}",
        f"d-i passwd/username string {data['username']}",
        f"d-i passwd/user-password password {data['user_password']}",
        f"d-i passwd/user-password-again password {data['user_password']}",
        "d-i user-setup/allow-password-weak boolean true",
        "",
        "### ============================================================",
        "### 🛠️  ЭТАП 6: ПАКЕТЫ И СЕРВИСЫ",
        "### ============================================================",
        "",
        "tasksel tasksel/first multiselect standard, ssh-server",
        "d-i pkgsel/include string openssh-server mc dosfstools iproute2 curl wget",
        "d-i pkgsel/upgrade select none",
        "d-i pkgsel/update-policy select none",
        "",
        "### ============================================================",
        "### 🕒  ЭТАП 7: ЛОКАЛИЗАЦИЯ ВРЕМЕНИ",
        "### ============================================================",
        "",
        "d-i clock-setup/utc boolean true",
        f"d-i time/zone string {data['timezone']}",
        "",
        "### ============================================================",
        "### 🧱  ЭТАП 8: УСТАНОВКА GRUB",
        "### ============================================================",
        "",
        "d-i grub-installer/only_debian boolean true",
        f"d-i grub-installer/bootdev string {disks[0]}",
        "",
        "### ============================================================",
        "### 📵  ЭТАП 9: ПРОШИВКИ",
        "### ============================================================",
        "",
        "d-i hw-detect/load_firmware boolean false",
        "",
        "### ============================================================",
        "### 🔧  ЭТАП 10: LATE_COMMAND (Post-install)",
        "### ============================================================",
        "",
        "d-i preseed/late_command string \\",
    ])

    late_lines = []
    if data.get('register_disk') == 'on':
        late_lines.extend([
            "# === 📡 Регистрация хоста на сервере === \\",
            "MAC=$(cat /sys/class/net/$(ip route|awk '/default/{print $5}')/address); \\",
            "IP=$(ip -4 -o addr show $(ip route|awk '/default/{print $5}') | awk '{split($4,a,\"/\"); print a[1]}'); \\",
            f"HOST={data['hostname']}; \\",
        ])
        if data.get('extended_registration') == 'on':
            late_lines.extend([
                "echo \"Disk info for $HOST ($IP):\" > /tmp/disk_info.$MAC; \\",
                "parted -l >> /tmp/disk_info.$MAC; \\",
                "lsblk >> /tmp/disk_info.$MAC; \\",
                "df -h >> /tmp/disk_info.$MAC; \\",
                f"wget -q --post-data \"mac=$MAC&ip=$IP&hostname=$HOST&stage=disk_partitioned&details=$(cat /tmp/disk_info.$MAC | base64)\" \"{data['ipxe_url']}\" || true; \\",
            ])
        else:
            late_lines.extend([
                f"wget -q --post-data \"mac=$MAC&ip=$IP&hostname=$HOST&stage=disk_partitioned\" \"{data['ipxe_url']}\" || true; \\",
            ])

    if data.get('install_base_packages') == 'on':
        late_lines.extend([
            "",
            "# === ⚙️ Установка базовых пакетов + шрифт === \\",
            "in-target apt-get update ; \\",
            "in-target apt-get install -y wget curl python3 python3-pip console-setup fonts-dejavu-core; \\",
        ])

    if data.get('enable_root_ssh') == 'on':
        late_lines.extend([
            "",
            "# === 🔐 Разрешить root-доступ по SSH === \\",
            "echo 'PermitRootLogin yes' > /target/etc/ssh/sshd_config.d/perms.conf; \\",
        ])

    if data.get('disable_sound') == 'on':
        late_lines.extend([
            "",
            "# === 🔇 Отключение звука === \\",
            "echo 'blacklist snd_hda_intel' > /target/etc/modprobe.d/disable-hdaudio.conf; \\",
            "in-target update-grub; \\",
            "in-target update-initramfs -u; \\",
        ])

    late_lines.extend([
        "",
        "# === 📚 APT-источники === \\",
        "echo '# Основной репозиторий' > /target/etc/apt/sources.list; \\",
    ])
    if data["mirror_mode"] == "default":
        late_lines.extend([
            f"echo 'deb {data['mirror_host']}/repository/debian-bookworm-proxy bookworm main contrib non-free non-free-firmware' >> /target/etc/apt/sources.list; \\",
            f"echo 'deb {data['mirror_host']}/repository/debian-bookworm-proxy bookworm-updates main contrib non-free non-free-firmware' >> /target/etc/apt/sources.list; \\",
            f"echo 'deb {data['mirror_host']}/repository/debian-security-proxy bookworm-security main contrib non-free non-free-firmware' >> /target/etc/apt/sources.list; \\",
            "in-target apt update; \\",
        ])
    else:
        for url in data.get("mirrors", []):
            late_lines.append(f"echo \"{url}\" >> /target/etc/apt/sources.list; \\")
        late_lines.append("in-target apt update; \\")

    if data.get('show_ip') == 'on':
        late_lines.extend([
            "",
            "# === 📟 IP в bash.bashrc === \\",
            "echo '# Ваш IP (физический интерфейс):' >> /target/etc/bash.bashrc; \\",
            "echo \"ip -4 -o addr show scope global | awk '{print \\$4}' | cut -d/ -f1 | head -n1\" >> /target/etc/bash.bashrc; \\",
            "echo '' >> /target/etc/bash.bashrc; \\",
        ])

    if data.get('enable_ansible') == 'on':
        late_lines.extend([
            "",
            "# === 🤖 Регистрация в Ansible === \\",
            f"wget -O /target/root/ansible-register.sh \"{data['ansible_script']}\" ; \\",
            "chmod +x /target/root/ansible-register.sh; \\",
            "echo '#!/bin/bash' > /target/etc/rc.local; \\",
            "echo 'sleep 30' >> /target/etc/rc.local; \\",
            "echo '/root/ansible-register.sh &' >> /target/etc/rc.local; \\",
            "echo 'exit 0' >> /target/etc/rc.local; \\",
            "chmod +x /target/etc/rc.local; \\",
            "in-target systemctl enable rc-local; \\",
        ])

    if data.get('fix_hostname') == 'on':
        late_lines.extend([
            "",
            "# === 🤖 Настройка hostname === \\",
            f"echo {data['hostname']} > /target/etc/hostname; \\",
            f"echo \"127.0.1.1 {data['hostname']}.localdomain {data['hostname']}\" >> /target/etc/hosts; \\",
        ])

    if data.get('disable_video') == 'on':
        late_lines.extend([
            "",
            "# === 🖥️ Отключение видеодрайвера === \\",
            "echo 'GRUB_CMDLINE_LINUX_DEFAULT=\"quiet nomodeset i915.modeset=0\"' >> /target/etc/default/grub; \\",
            "echo 'blacklist i915' > /target/etc/modprobe.d/disable-i915.conf; \\",
            "echo 'blacklist intel_guc' >> /target/etc/modprobe.d/disable-i915.conf; \\",
            "in-target update-grub; \\",
            "in-target update-initramfs -u; \\",
        ])

    if data.get('enable_font') == 'on':
        late_lines.extend([
            "",
            "# === 😍 Красивый шрифт в TTY === \\",
            f"echo 'FONTFACE=\"{data['font_face']}\"' > /target/etc/default/console-setup; \\",
            f"echo 'FONTSIZE=\"{data['font_size']}\"' >> /target/etc/default/console-setup; \\",
            "echo 'FONT=' >> /target/etc/default/console-setup; \\",
            "echo 'VIDEOMODE=' >> /target/etc/default/console-setup; \\",
            "in-target setupcon; \\",
        ])

    late_lines.extend([
        "",
        "### 🚀 Завершение установки",
        "d-i finish-install/reboot_in_progress note",
    ])

    preseed_lines.extend(late_lines)
    return '\n'.join(preseed_lines)
