// Preseed builder logic
function generatePreseed() {
  const hostname = document.getElementById('hostname').value || 'debian';
  const domain = document.getElementById('domain').value || 'local';
  const rootPass = document.getElementById('root-pass').value || 'root';
  const timezone = document.getElementById('timezone').value || 'UTC';
  const text = [
    `d-i netcfg/get_hostname string ${hostname}`,
    `d-i netcfg/get_domain string ${domain}`,
    'd-i netcfg/choose_interface select auto',
    'd-i netcfg/disable_dhcp boolean false',
    `d-i time/zone string ${timezone}`,
    'd-i clock-setup/utc boolean true',
    `d-i passwd/root-password password ${rootPass}`,
    `d-i passwd/root-password-again password ${rootPass}`,
    'd-i pkgsel/include string openssh-server curl',
    'd-i finish-install/reboot_in_progress note'
  ].join('\n');
  document.getElementById('preseed-text').value = text + '\n';
}
async function savePreseed() {
  const content = document.getElementById('preseed-text').value;
  try {
    const res = await fetch('/api/preseed', {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain' },
      body: content
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.msg || res.statusText);
    }
    alert('Сохранено');
  } catch (e) {
    alert('Ошибка: ' + e.message);
  }
}
document.getElementById('generate').onclick = generatePreseed;
document.getElementById('save').onclick = savePreseed;
