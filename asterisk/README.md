# Asterisk

В каталоге находятся инструкции по установке и базовой проверке работы Asterisk.

## Установка
```bash
sudo apt-get install asterisk
```

## Проверка
```bash
sudo asterisk -rvvv
*CLI> dahdi show channels
```
Если каналы отображаются, система готова к работе.

## Перезапуск после изменений
```bash
sudo systemctl restart asterisk
```
