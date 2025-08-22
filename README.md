# PXE Watch

PXE Watch — утилита на базе Flask для отслеживания хостов во время сетевого развёртывания и мониторинга выполнения playbook'ов Ansible. Она предоставляет REST API для регистрации машин, минимальный веб-интерфейс и фоновые задачи, которые анализируют журналы Ansible, обновляя статус выполнения для каждого хоста.

## Возможности
- Регистрация хостов по MAC-адресу, IP, стадии и описанию.
- Простой веб-интерфейс и точки доступа для чтения логов.
- Фоновый поток, отслеживающий вывод `journalctl` для результатов playbook'ов Ansible.

## Требования
- Python 3.11+
- SQLite (файл `pxe.db`)
- [Драйверы и утилиты DAHDI](https://www.asterisk.org/dahdi/)
- [Asterisk PBX](https://www.asterisk.org/)

Проект напрямую не взаимодействует с DAHDI и Asterisk, однако типичное развёртывание включает телекоммуникационный стек. Корректная установка этих компонентов обеспечивает доступность аппаратных каналов для сервисов на базе данного приложения.

## Установка
```bash
# клонируем репозиторий
git clone https://example.com/pxe-watch.git
cd pxe-watch

# создаём и активируем виртуальное окружение
python -m venv .venv
source .venv/bin/activate

# устанавливаем зависимости Python
pip install -r requirements.txt
```

Создайте файл `.env` или экспортируйте переменные окружения для переопределения значений по умолчанию, определённых в `config.py`.

## Запуск
```bash
python app.py
```
Сервис слушает порт 5000. Веб-интерфейс доступен по адресу `http://localhost:5000`.

## Настройка DAHDI
1. Установите пакеты:
   ```bash
   sudo apt-get install dahdi dahdi-dkms dahdi-tools
   ```
2. Загрузите и проверьте драйверы:
   ```bash
   sudo modprobe dahdi
   sudo dahdi_genconf
   sudo dahdi_cfg -vv
   ```
3. Убедитесь, что аппаратные каналы отображаются в `/proc/dahdi/`.

Подробнее см. в каталоге [`dahdi`](dahdi/README.md).

## Настройка Asterisk
1. Установите Asterisk:
   ```bash
   sudo apt-get install asterisk
   ```
2. Проверьте обнаружение каналов DAHDI:
   ```bash
   sudo asterisk -rvvv
   *CLI> dahdi show channels
   ```
3. При необходимости включите или настройте модули в `/etc/asterisk/`, затем перезапустите сервис:
   ```bash
   sudo systemctl restart asterisk
   ```

Подробные инструкции находятся в каталоге [`asterisk`](asterisk/README.md).

## Лицензия
MIT
