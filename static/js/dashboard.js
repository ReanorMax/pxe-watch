    let playbookEditor;
    let ansibleLogLimit = 100;
    let autoScroll = true;
    document.addEventListener('DOMContentLoaded', () => {
      playbookEditor = CodeMirror(document.getElementById('playbook-editor'), {
        value: "",
        mode: "text/x-yaml",
        theme: "dracula",
        lineNumbers: true,
        lineWrapping: true,
        indentUnit: 2,
        tabSize: 2,
        indentWithTabs: false,
        styleActiveLine: true,
        matchBrackets: true,
        autoCloseBrackets: true,
        extraKeys: { Tab: cm => cm.replaceSelection("  ", "end") }
      });
    });
    const overlay = document.getElementById('overlay');
    const modals = document.querySelectorAll('.modal');
    function openModal(modal) {
      overlay.style.display = 'block';
      modal.style.display = 'flex';
    }
    function closeModal(modal) {
      overlay.style.display = 'none';
      modal.style.display = 'none';
    }
    function updatePortainerLinks() {
        const rows = document.querySelectorAll('#hosts-table-body tr');
        rows.forEach(row => {
            const ip = row.dataset.ip;
            const portainerLink = row.querySelector('.portainer-link');
            if (portainerLink) {
                if (ip && ip !== '—') {
                    const url = `http://${ip}:9000`;
                    portainerLink.href = url;
                    portainerLink.style.display = 'inline-flex';
                    portainerLink.title = `Portainer (${url})`;
                } else {
                    portainerLink.style.display = 'none';
                    portainerLink.href = '#';
                    portainerLink.title = 'Portainer (IP неизвестен)';
                }
            }
        });
    }
    document.addEventListener('DOMContentLoaded', updatePortainerLinks);

    async function refreshHosts() {
      try {
        const res = await fetch('/api/hosts/status');
        if (!res.ok) throw new Error();
        const data = await res.json();
        const tbody = document.getElementById('hosts-table-body');
        tbody.innerHTML = '';
        data.hosts.forEach(h => {
          const tr = document.createElement('tr');
          tr.dataset.ip = h.ip;
          tr.dataset.mac = h.mac;
          tr.innerHTML = `
            <td>${h.mac}</td>
            <td>${h.ip}</td>
            <td>${h.stage}</td>
            <td><time datetime="${h.last}">${h.last}</time></td>
            <td class="status ${h.online ? 'online' : 'offline'}">
              <i class="fa fa-circle"></i>
              <span>${h.online ? 'Online' : 'Offline'}</span>
            </td>
            <td>
              <a class="btn-portainer portainer-link" href="http://${h.ip}:9000" target="_blank" rel="noopener noreferrer" title="Portainer" style="display: ${h.ip && h.ip !== '—' ? 'inline-flex' : 'none'};">
                <i class="fab fa-docker"></i> Portainer
              </a>
            </td>
            <td class="actions-cell">
              <button class="btn-wol" data-mac="${h.mac}" title="Включить (Wake-on-LAN)">
                <i class="fas fa-plug"></i> WOL
              </button>
              <button class="btn-shutdown" data-ip="${h.ip}" title="Выключить">
                <i class="fas fa-power-off"></i> Shutdown
              </button>
              <button class="btn-reboot" data-ip="${h.ip}" title="Перезагрузить">
                <i class="fa fa-sync-alt"></i> reboot
              </button>
            </td>
          `;
          tbody.appendChild(tr);
        });
        document.querySelector('.stat-card.total .stat-number').textContent = data.total_hosts;
        document.querySelector('.stat-card.online .stat-number').textContent = data.online_hosts;
        document.querySelector('.stat-card.installing .stat-number').textContent = data.installing_hosts;
        document.querySelector('.stat-card.completed .stat-number').textContent = data.completed_hosts;
        updatePortainerLinks();
      } catch (e) {
        console.error('Ошибка обновления списка хостов:', e);
      }
    }

    document.addEventListener('DOMContentLoaded', () => {
      refreshHosts();
      setInterval(refreshHosts, 10000);
    });
    async function openModalWithContent(modalId, apiUrl, contentElementId, isPlaybook = false) {
      const modal = document.getElementById(modalId);
      try {
        const res = await fetch(apiUrl);
        if (!res.ok) throw new Error();
        const content = await res.text();
        if (isPlaybook && playbookEditor) {
          playbookEditor.setValue(content);
          setTimeout(() => playbookEditor.refresh(), 100);
        } else {
          const el = document.getElementById(contentElementId);
          if (el) el.value = content;
        }
        if (contentElementId === 'ipxe-content') setIpxeEdit(false);
        if (contentElementId === 'dnsmasq-content') setDnsmasqEdit(false);
        openModal(modal);
      } catch (e) {
        alert(`Ошибка загрузки: ${e.message}`);
      }
    }
    async function saveContentToApi(apiUrl, contentElementId, successCallback, isPlaybook = false) {
      try {
        const content = isPlaybook && playbookEditor
          ? playbookEditor.getValue()
          : document.getElementById(contentElementId).value;
        const res = await fetch(apiUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'text/plain' },
          body: content
        });
        if (!res.ok) throw new Error((await res.json()).msg);
        alert('Сохранено.');
        if (successCallback) successCallback();
      } catch (e) {
        alert('Ошибка сохранения: ' + e.message);
      }
    }
    [
      { btn: 'edit-ipxe', modal: 'ipxe-modal', api: '/api/ipxe', elem: 'ipxe-content' },
      { btn: 'edit-dnsmasq', modal: 'dnsmasq-modal', api: '/api/dnsmasq', elem: 'dnsmasq-content' },
      { btn: 'edit-inventory', modal: 'inventory-modal', api: '/api/ansible/inventory', elem: 'inventory-content' },
      { btn: 'edit-playbook', modal: 'playbook-modal', api: '/api/ansible/playbook', isPlaybook: true }
    ].forEach(config => {
      const btn = document.getElementById(config.btn);
      if (btn) btn.onclick = () => openModalWithContent(
        config.modal,
        config.api,
        config.elem,
        config.isPlaybook
      );
    });
    document.querySelectorAll('.close-modal').forEach(btn => {
      btn.onclick = () => {
        const modal = document.getElementById(btn.dataset.modal);
        if (modal) closeModal(modal);
      };
    });
    function setupSaveButton(buttonId, apiPath, contentId, onSuccess, isPlaybook = false) {
      document.getElementById(buttonId).onclick = () => {
        saveContentToApi(apiPath, contentId, onSuccess, isPlaybook);
      };
    }
    setupSaveButton('save-ipxe', '/api/ipxe', 'ipxe-content', () => closeModal(document.getElementById('ipxe-modal')));
    setupSaveButton('save-dnsmasq', '/api/dnsmasq', 'dnsmasq-content', () => closeModal(document.getElementById('dnsmasq-modal')));
    setupSaveButton('save-playbook', '/api/ansible/playbook', null, () => closeModal(document.getElementById('playbook-modal')), true);
    setupSaveButton('save-inventory', '/api/ansible/inventory', 'inventory-content', () => closeModal(document.getElementById('inventory-modal')));

    function setIpxeEdit(editing) {
      const textarea = document.getElementById('ipxe-content');
      const saveBtn = document.getElementById('save-ipxe');
      const editBtn = document.getElementById('edit-ipxe-btn');
      textarea.readOnly = !editing;
      saveBtn.style.display = editing ? 'inline-flex' : 'none';
      editBtn.innerHTML = editing
        ? '<i class="fa fa-times"></i> Отмена'
        : '<i class="fa fa-edit"></i> Редактировать';
    }

    function setDnsmasqEdit(editing) {
      const textarea = document.getElementById('dnsmasq-content');
      const saveBtn = document.getElementById('save-dnsmasq');
      const editBtn = document.getElementById('edit-dnsmasq-btn');
      const addBtn = document.getElementById('add-dhcp-host');
      textarea.readOnly = !editing;
      saveBtn.style.display = editing ? 'inline-flex' : 'none';
      addBtn.style.display = editing ? 'inline-flex' : 'none';
      editBtn.innerHTML = editing
        ? '<i class="fa fa-times"></i> Отмена'
        : '<i class="fa fa-edit"></i> Редактировать';
    }

    document.getElementById('edit-ipxe-btn').onclick = async () => {
      const textarea = document.getElementById('ipxe-content');
      if (textarea.readOnly) {
        setIpxeEdit(true);
      } else {
        setIpxeEdit(false);
        const res = await fetch('/api/ipxe');
        textarea.value = await res.text();
      }
    };

    document.getElementById('edit-dnsmasq-btn').onclick = async () => {
      const textarea = document.getElementById('dnsmasq-content');
      if (textarea.readOnly) {
        setDnsmasqEdit(true);
      } else {
        setDnsmasqEdit(false);
        const res = await fetch('/api/dnsmasq');
        textarea.value = await res.text();
      }
    };

    document.getElementById('edit-preseed').onclick = openPreseedModal;

    async function openPreseedModal() {
      try {
        const res = await fetch('/api/preseed/list');
        const data = await res.json();
        const select = document.getElementById('preseed-select');
        select.innerHTML = '';
        data.files.forEach(name => {
          const opt = document.createElement('option');
          opt.value = name;
          opt.textContent = name;
          if (name === data.active) opt.selected = true;
          select.appendChild(opt);
        });
        await loadPreseedContent();
        setPreseedEdit(false);
        openModal(document.getElementById('preseed-modal'));
      } catch (e) {
        alert('Ошибка загрузки preseed: ' + e.message);
      }
    }

    async function loadPreseedContent() {
      const name = document.getElementById('preseed-select').value;
      if (!name) return;
      const res = await fetch(`/api/preseed?name=${encodeURIComponent(name)}`);
      const text = await res.text();
      document.getElementById('preseed-content').value = text;
    }

    function setPreseedEdit(editing) {
      const textarea = document.getElementById('preseed-content');
      const saveBtn = document.getElementById('save-preseed');
      const editBtn = document.getElementById('edit-preseed-btn');
      textarea.readOnly = !editing;
      saveBtn.style.display = editing ? 'inline-flex' : 'none';
      editBtn.innerHTML = editing
        ? '<i class="fa fa-times"></i> Отмена'
        : '<i class="fa fa-edit"></i> Редактировать';
    }

    document.getElementById('preseed-select').onchange = () => {
      loadPreseedContent();
      setPreseedEdit(false);
    };

    document.getElementById('edit-preseed-btn').onclick = () => {
      const textarea = document.getElementById('preseed-content');
      if (textarea.readOnly) {
        setPreseedEdit(true);
      } else {
        setPreseedEdit(false);
        loadPreseedContent();
      }
    };

    document.getElementById('save-preseed').onclick = () => {
      const name = document.getElementById('preseed-select').value;
      saveContentToApi(`/api/preseed?name=${encodeURIComponent(name)}`, 'preseed-content', () => setPreseedEdit(false));
    };

    document.getElementById('preseed-activate').onclick = async () => {
      const name = document.getElementById('preseed-select').value;
      try {
        const res = await fetch('/api/preseed/activate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name })
        });
        if (!res.ok) throw new Error((await res.json()).msg);
        alert('Активирован.');
        openPreseedModal();
      } catch (e) {
        alert('Ошибка активации: ' + e.message);
      }
    };

    document.getElementById('preseed-add').onclick = async () => {
      const name = prompt('Имя файла (например, custom.cfg):');
      if (!name) return;
      try {
        const res = await fetch('/api/preseed/create', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name })
        });
        if (!res.ok) throw new Error((await res.json()).msg);
        await openPreseedModal();
        document.getElementById('preseed-select').value = name;
        await loadPreseedContent();
        setPreseedEdit(true);
      } catch (e) {
        alert('Ошибка создания: ' + e.message);
      }
    };

    document.getElementById('preseed-delete').onclick = async () => {
      const name = document.getElementById('preseed-select').value;
      if (!name || !confirm(`Удалить ${name}?`)) return;
      try {
        const res = await fetch('/api/preseed/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name })
        });
        if (!res.ok) throw new Error((await res.json()).msg);
        alert('Удалено.');
        openPreseedModal();
      } catch (e) {
        alert('Ошибка удаления: ' + e.message);
      }
    };
    let currentFilesPath = '';
    const baseFilesPath = document.getElementById('files-modal-title').textContent.replace(/^Файлы\s*/, '');
    async function loadFilesList() {
        const listBody = document.getElementById('files-simple-list-body');
        listBody.innerHTML = '<tr><td colspan="3" style="text-align: center;">Загрузка...</td></tr>';
        try {
            const res = await fetch(`/api/ansible/files?path=${encodeURIComponent(currentFilesPath)}`);
            const data = await res.json();
            listBody.innerHTML = '';
            if (data.error) {
                listBody.innerHTML = `<tr><td colspan="3" style="color:var(--danger);">Ошибка: ${data.error}</td></tr>`;
                return;
            }
            const title = document.getElementById('files-modal-title');
            title.textContent = `Файлы ${baseFilesPath}${currentFilesPath ? '/' + currentFilesPath : ''}`;
            if (currentFilesPath) {
                const upTr = document.createElement('tr');
                upTr.innerHTML = '<td colspan="3" style="cursor:pointer">..</td>';
                upTr.onclick = () => {
                    currentFilesPath = data.parent;
                    loadFilesList();
                };
                listBody.appendChild(upTr);
            }
            if (data.files.length === 0) {
                const emptyTr = document.createElement('tr');
                emptyTr.innerHTML = '<td colspan="3" style="text-align: center; font-style: italic;">Файлы не найдены</td>';
                listBody.appendChild(emptyTr);
                return;
            }
            data.files.forEach(file => {
                const tr = document.createElement('tr');
                const escapedName = file.name.replace(/&/g, "&amp;").replace(/</g, "<").replace(/>/g, ">").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
                if (file.is_dir) {
                    tr.innerHTML = `<td title="${escapedName}" style="cursor:pointer">${escapedName}</td><td>-</td><td>${file.modified}</td>`;
                    tr.querySelector('td').onclick = () => {
                        currentFilesPath = currentFilesPath ? `${currentFilesPath}/${file.name}` : file.name;
                        loadFilesList();
                    };
                } else {
                    tr.innerHTML = `<td title="${escapedName}">${escapedName}</td><td>${file.size}</td><td>${file.modified}</td>`;
                }
                listBody.appendChild(tr);
            });
        } catch (e) {
            console.error("Ошибка при загрузке списка файлов:", e);
            listBody.innerHTML = `<tr><td colspan="3" style="color:var(--danger);">Ошибка загрузки: ${e.message}</td></tr>`;
        }
    }
    document.getElementById('manage-files').onclick = () => {
        currentFilesPath = '';
        openModal(document.getElementById('files-modal'));
        loadFilesList();
    };
    document.getElementById('add-dhcp-host').onclick = () => {
      const mac = prompt('MAC:');
      const ip = prompt('IP:');
      if (mac && ip) {
        const textarea = document.getElementById('dnsmasq-content');
        textarea.value = `dhcp-host=${mac},${ip},12h\n${textarea.value}`;
      }
    };
    document.getElementById('clear-db').onclick = async () => {
      if (!confirm('Удалить базу данных?')) return;
      try {
        const res = await fetch('/api/clear-db', { method: 'POST' });
        if (!res.ok) throw new Error((await res.json()).msg);
        alert('База очищена.');
        location.reload();
      } catch (e) {
        alert('Ошибка: ' + e.message);
      }
    };
    document.getElementById('toggle-ansible').onclick = () => {
      const p = document.getElementById('ansible-panel');
      p.style.display = p.style.display === 'none' ? 'block' : 'none';
      if (p.style.display === 'block') {
        autoScroll = true;
        loadAnsibleLog();
      }
    };
    async function loadAnsibleLog() {
      try {
        const res = await fetch(`/api/logs/ansible?limit=${ansibleLogLimit}`);
        const lines = await res.json();
        const logEl = document.getElementById('ansible-log');
        logEl.innerHTML = '';
        lines.forEach(line => {
            const div = document.createElement('div');
            div.innerHTML = line;
            logEl.appendChild(div);
        });
        if (autoScroll) setTimeout(() => logEl.scrollTop = logEl.scrollHeight, 0);
      } catch (e) {
        document.getElementById('ansible-log').innerHTML = `<span style="color:#ff6b6b">Ошибка: ${e.message}</span>`;
      }
    }

    setInterval(loadAnsibleLog, 3000);
    const ansibleLogEl = document.getElementById('ansible-log');
    ansibleLogEl.addEventListener('scroll', () => {
      const atBottom = ansibleLogEl.scrollTop + ansibleLogEl.clientHeight >= ansibleLogEl.scrollHeight - 5;
      autoScroll = atBottom;
    });
    document.getElementById('ansible-log-limit').addEventListener('change', e => {
      ansibleLogLimit = parseInt(e.target.value, 10);
      loadAnsibleLog();
    });
    document.getElementById('collapse-ansible-log').onclick = () => {
      const log = document.getElementById('ansible-log');
      const btn = document.getElementById('collapse-ansible-log');
      if (log.style.display === 'none') {
        log.style.display = 'block';
        btn.innerHTML = '<i class="fa fa-chevron-up"></i>';
      } else {
        log.style.display = 'none';
        btn.innerHTML = '<i class="fa fa-chevron-down"></i>';
      }
    };
    document.getElementById('hosts-table-body').addEventListener('click', async (e) => {
      if (e.target.closest('.btn-reboot')) {
        const ip = e.target.closest('.btn-reboot').dataset.ip;
        if (!ip || ip === '—') return alert('Неверный IP.');
        if (!confirm(`Перезагрузить ${ip}?`)) return;
        try {
          const res = await fetch('/api/host/reboot', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ip })
          });
          if (!res.ok) throw new Error((await res.json()).msg);
          const data = await res.json();
          alert(data.msg || 'Команда отправлена.');
        } catch (e) {
          alert('Ошибка: ' + e.message);
        }
      }
      else if (e.target.closest('.btn-wol')) {
        const mac = e.target.closest('.btn-wol').dataset.mac;
        if (!mac || mac === '—') return alert('Неверный MAC-адрес.');
        if (!confirm(`Отправить Wake-on-LAN на ${mac}?`)) return;
        try {
          const res = await fetch('/api/host/wol', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mac })
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.msg || 'Неизвестная ошибка');
          alert(data.msg || 'Команда WOL отправлена.');
        } catch (e) {
          alert('Ошибка: ' + e.message);
        }
      }
      else if (e.target.closest('.btn-shutdown')) {
        const ip = e.target.closest('.btn-shutdown').dataset.ip;
        if (!ip || ip === '—') return alert('Неверный IP.');
        if (!confirm(`Выключить ${ip}?`)) return;
        try {
          const res = await fetch('/api/host/shutdown', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ip })
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.msg || 'Неизвестная ошибка');
          alert(data.msg || 'Команда Shutdown отправлена.');
        } catch (e) {
          alert('Ошибка: ' + e.message);
        }
      }
    });
    overlay.onclick = () => modals.forEach(closeModal);
