# DAHDI

Каталог содержит инструкции по установке и проверке драйверов DAHDI.

## Установка
```bash
sudo apt-get install dahdi dahdi-dkms dahdi-tools
```

## Инициализация
```bash
sudo modprobe dahdi
sudo dahdi_genconf
sudo dahdi_cfg -vv
```

## Проверка
```bash
cat /proc/dahdi/*
```
Убедитесь, что оборудование обнаружено и каналы активны.
