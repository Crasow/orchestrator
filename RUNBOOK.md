# Runbook — AI Services Orchestrator

Шпаргалка по деплою, обновлению и обслуживанию сервиса.

---

## Содержание

1. [Первый деплой с нуля](#1-первый-деплой-с-нуля)
2. [Управление ключами через Admin API](#2-управление-ключами-через-admin-api)
3. [Обновление сервиса](#3-обновление-сервиса)
4. [Управление базой данных](#4-управление-базой-данных)
5. [Дампы и восстановление](#5-дампы-и-восстановление)
6. [Полезные команды](#6-полезные-команды)
7. [Решение проблем](#7-решение-проблем)

---

## 1. Первый деплой с нуля

### 1.1 Требования на сервере

```bash
docker --version        # Docker 24+
docker compose version  # Compose v2 (не docker-compose)
```

Установка Docker если нет: https://docs.docker.com/engine/install/ubuntu/

### 1.2 Клонировать репозиторий

```bash
git clone https://github.com/Crasow/orchestrator.git
cd orchestrator
```

### 1.3 Создать папки

```bash
mkdir -p credentials secrets
```

### 1.4 Положить credentials

```
credentials/
├── gemini/
│   └── api_keys.json          # Gemini API ключи
└── vertex/                    # Vertex service account JSON файлы
    ├── account1.json
    └── account2.json
```

Формат `api_keys.json` — смотри `API_DOCS.md` Part 4.

> После деплоя ключи можно добавлять/удалять через Admin API (секция 2) без перезапуска.

### 1.5 Создать .env

```bash
cp .env.example .env
nano .env
```

Минимально нужно заполнить:

```env
SECURITY__ADMIN_SECRET=<длинная случайная строка>
SECURITY__ADMIN_USERNAME=admin
SECURITY__ADMIN_PASSWORD_HASH=    # заполним ниже
```

Сгенерировать `ADMIN_SECRET`:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 1.6 Собрать образ и запустить

```bash
# ВАЖНО: только -f docker-compose.yaml, без override (иначе запустится dev режим)
docker compose -f docker-compose.yaml up -d --build
```

### 1.7 Сгенерировать хэш пароля администратора

```bash
docker compose -f docker-compose.yaml run --rm orchestrator \
  python -c "from app.security.auth import AuthManager; print(AuthManager().hash_password('твой-пароль'))"
```

Скопировать результат (строку вида `pbkdf2_sha256$...`) в `.env`:

```env
SECURITY__ADMIN_PASSWORD_HASH=pbkdf2_sha256$...
```

Перезапустить с новым .env:

```bash
docker compose -f docker-compose.yaml up -d
```

### 1.8 Применить миграции БД

```bash
docker compose -f docker-compose.yaml exec orchestrator alembic upgrade head
```

> Если таблицы уже существуют но `alembic_version` нет (перенос старой БД):
> ```bash
> docker compose -f docker-compose.yaml exec orchestrator alembic stamp head
> ```

### 1.9 Проверить что всё работает

```bash
curl http://localhost:8000/health
```

Ожидаемый ответ:
```json
{"status": "healthy", "database": "connected", "gemini_keys": 5, "vertex_credentials": 5}
```

---

## 2. Управление ключами через Admin API

Ключи и сервис-аккаунты можно добавлять, обновлять и удалять через Admin API — без SSH и перезапуска сервиса. Все операции автоматически сохраняют файл на диск и перезагружают ротатор.

> Для работы нужен авторизованный запрос. Получить cookie можно через `POST /admin/login`.

### 2.1 Gemini ключи

```bash
# Список ключей (замаскированные)
curl -b cookies.txt http://localhost:8000/admin/keys/gemini

# Добавить ключи
curl -b cookies.txt -X POST http://localhost:8000/admin/keys/gemini \
  -H "Content-Type: application/json" \
  -d '{"keys": ["AIzaSyNew1...", "AIzaSyNew2..."]}'

# Заменить ключ по индексу
curl -b cookies.txt -X PUT http://localhost:8000/admin/keys/gemini/0 \
  -H "Content-Type: application/json" \
  -d '{"key": "AIzaSyReplaced..."}'

# Удалить ключ по индексу
curl -b cookies.txt -X DELETE http://localhost:8000/admin/keys/gemini/0
```

### 2.2 Vertex сервис-аккаунты

```bash
# Список сервис-аккаунтов (project_id + filename)
curl -b cookies.txt http://localhost:8000/admin/keys/vertex

# Загрузить новый сервис-аккаунт
curl -b cookies.txt -X POST http://localhost:8000/admin/keys/vertex \
  -H "Content-Type: application/json" \
  -d '{
    "filename": "new-project-sa.json",
    "credential": {
      "type": "service_account",
      "project_id": "new-project-789",
      "private_key": "-----BEGIN RSA PRIVATE KEY-----\n...",
      "client_email": "sa@new-project.iam.gserviceaccount.com"
    }
  }'

# Заменить сервис-аккаунт (по project_id)
curl -b cookies.txt -X PUT http://localhost:8000/admin/keys/vertex/my-project-123 \
  -H "Content-Type: application/json" \
  -d '{"credential": {"type": "service_account", "project_id": "my-project-123", "private_key": "..."}}'

# Удалить сервис-аккаунт (по project_id)
curl -b cookies.txt -X DELETE http://localhost:8000/admin/keys/vertex/my-project-123
```

### 2.3 Получение cookie для curl

```bash
# Логин — cookie сохранится в файл
curl -c cookies.txt -X POST http://localhost:8000/admin/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "ваш-пароль"}'
```

> Полная документация по всем эндпоинтам — в [API_DOCS.md](API_DOCS.md).

---

## 3. Обновление сервиса

### 3.1 Обычное обновление (без изменений схемы БД)

```bash
git pull
docker compose -f docker-compose.yaml up -d --build
```

### 3.2 Обновление с миграциями БД

Когда добавили новые колонки/таблицы в моделях:

```bash
git pull

# Пересобрать и перезапустить
docker compose -f docker-compose.yaml up -d --build

# Применить новые миграции
docker compose -f docker-compose.yaml exec orchestrator alembic upgrade head
```

### 3.3 Как понять нужны ли миграции?

```bash
# Показывает текущую версию и есть ли pending миграции
docker compose -f docker-compose.yaml exec orchestrator alembic current

# Показывает историю всех миграций и какие применены
docker compose -f docker-compose.yaml exec orchestrator alembic history
```

Если `current` показывает не `(head)` — нужно запустить `upgrade head`.

---

## 4. Управление базой данных

### 4.1 Alembic — шпаргалка команд

```bash
# Текущая версия схемы
alembic current

# История миграций
alembic history

# Применить все pending миграции
alembic upgrade head

# Применить следующую миграцию (только одну)
alembic upgrade +1

# Откатить последнюю миграцию (ОСТОРОЖНО: данные могут удалиться)
alembic downgrade -1

# Откатить до конкретной версии
alembic downgrade 001

# Пометить версию без выполнения SQL (для синхронизации состояния)
alembic stamp head

# Показать SQL который будет выполнен (без применения)
alembic upgrade head --sql
```

Все команды запускать через docker:
```bash
docker compose -f docker-compose.yaml exec orchestrator alembic <команда>
```

### 4.2 Добавить новую колонку — полный цикл

**Шаг 1.** Добавить в модель (`app/db/models.py`):
```python
cost = Column(Float, nullable=True)
```

**Шаг 2.** Сгенерировать миграцию (локально или на сервере):
```bash
alembic revision --autogenerate -m "add cost to requests"
```

Проверить сгенерированный файл в `alembic/versions/` — alembic иногда ошибается, особенно с JSONB и кастомными типами.

**Шаг 3.** Закоммитить файл миграции вместе с изменением модели:
```bash
git add alembic/versions/002_add_cost_to_requests.py app/db/models.py
git commit -m "Add cost column to requests"
git push
```

**Шаг 4.** На сервере:
```bash
git pull
docker compose -f docker-compose.yaml up -d --build
docker compose -f docker-compose.yaml exec orchestrator alembic upgrade head
```

### 4.3 Подключиться к PostgreSQL напрямую

```bash
docker compose -f docker-compose.yaml exec postgres psql -U orchestrator -d orchestrator
```

Полезные SQL команды внутри psql:
```sql
-- Список таблиц
\dt

-- Структура таблицы
\d requests

-- Выйти
\q
```

---

## 5. Дампы и восстановление

### 5.1 Сделать дамп всей БД

```bash
docker compose -f docker-compose.yaml exec postgres \
  pg_dump -U orchestrator orchestrator > backup_$(date +%Y%m%d_%H%M%S).sql
```

Файл сохранится на сервере в текущей директории.

### 5.2 Сделать дамп одной таблицы

```bash
docker compose -f docker-compose.yaml exec postgres \
  pg_dump -U orchestrator -t requests orchestrator > backup_requests_$(date +%Y%m%d).sql
```

### 5.3 Восстановить из дампа

```bash
# ОСТОРОЖНО: перезапишет данные
docker compose -f docker-compose.yaml exec -T postgres \
  psql -U orchestrator -d orchestrator < backup_20260225_120000.sql
```

### 5.4 Перенести дамп на локальную машину

```bash
# С сервера на локальную (выполнять локально)
scp revouser@91.98.183.136:~/orchestrator/backup_20260225.sql ./
```

### 5.5 Автоматические дампы (cron)

На сервере добавить в crontab:
```bash
crontab -e
```

```cron
# Дамп каждую ночь в 3:00, хранить 7 дней
0 3 * * * cd ~/orchestrator && docker compose -f docker-compose.yaml exec -T postgres pg_dump -U orchestrator orchestrator > ~/backups/backup_$(date +\%Y\%m\%d).sql && find ~/backups -name "backup_*.sql" -mtime +7 -delete
```

```bash
mkdir -p ~/backups
```

---

## 6. Полезные команды

### Логи

```bash
# Следить за логами в реальном времени
docker compose -f docker-compose.yaml logs -f orchestrator

# Последние 100 строк
docker compose -f docker-compose.yaml logs --tail=100 orchestrator

# Логи PostgreSQL
docker compose -f docker-compose.yaml logs -f postgres
```

### Статус контейнеров

```bash
docker compose -f docker-compose.yaml ps
```

### Перезапустить без пересборки

```bash
docker compose -f docker-compose.yaml restart orchestrator
```

### Полная остановка

```bash
# Остановить контейнеры (данные БД сохранятся в volume)
docker compose -f docker-compose.yaml down

# Остановить и удалить данные БД (ОСТОРОЖНО)
docker compose -f docker-compose.yaml down -v
```

### Зайти внутрь контейнера

```bash
docker compose -f docker-compose.yaml exec orchestrator bash
```

### Посмотреть использование ресурсов

```bash
docker stats
```

---

## 7. Решение проблем

### Сервис не стартует

```bash
# Смотреть логи
docker compose -f docker-compose.yaml logs orchestrator

# Проверить health
curl http://localhost:8000/health
```

### `ModuleNotFoundError: No module named 'app'` в alembic

Проверить что в `alembic.ini` есть:
```ini
prepend_sys_path = .
```

Если есть — пересобрать образ:
```bash
docker compose -f docker-compose.yaml up -d --build
```

### `DuplicateTableError` при миграции

Таблицы уже существуют, но alembic не знает об этом. Пометить текущее состояние:
```bash
docker compose -f docker-compose.yaml exec orchestrator alembic stamp head
```

### БД не поднимается

```bash
# Проверить что postgres здоров
docker compose -f docker-compose.yaml ps
docker compose -f docker-compose.yaml logs postgres
```

### Забыл пароль от админки

Сгенерировать новый хэш и обновить `.env`:
```bash
docker compose -f docker-compose.yaml run --rm orchestrator \
  python -c "from app.security.auth import AuthManager; print(AuthManager().hash_password('новый-пароль'))"
```

Вставить хэш в `.env`, перезапустить:
```bash
docker compose -f docker-compose.yaml up -d
```

### Откатить последнее обновление

```bash
# Откатить миграцию если была
docker compose -f docker-compose.yaml exec orchestrator alembic downgrade -1

# Вернуться на предыдущий коммит
git log --oneline -5   # найти нужный хэш
git checkout <хэш>
docker compose -f docker-compose.yaml up -d --build
```

---

## Структура проекта (справочно)

```
orchestrator/
├── app/
│   ├── api/            # HTTP эндпоинты (proxy.py, admin.py)
│   ├── config.py       # все настройки через .env
│   ├── db/             # SQLAlchemy модели и engine
│   ├── security/       # JWT, шифрование, auth
│   └── services/       # ротаторы ключей, статистика
├── alembic/
│   ├── env.py          # конфиг подключения для миграций
│   └── versions/       # файлы миграций
├── alembic.ini         # настройки alembic
├── docker-compose.yaml         # продакшн
├── docker-compose.override.yml # дев (hot reload, порт БД)
├── .env.example        # шаблон переменных окружения
├── API_DOCS.md         # документация API
└── RUNBOOK.md          # этот файл
```
