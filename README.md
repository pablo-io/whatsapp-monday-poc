# WhatsApp ↔ Monday.com (POC)

## Objetivo

Prueba de concepto para recibir y responder mensajes de WhatsApp directamente desde un board de Monday.com. Prioriza velocidad y simplicidad de implementación por encima de robustez de producción: usa el motor no oficial de WhatsApp (Evolution API / Baileys) en lugar de la API oficial de Meta, ya que esta última requiere verificación de Business Manager que puede tardar días. **Este enfoque viola los términos de servicio de WhatsApp y conlleva riesgo de bloqueo del número** — solo debe usarse con un número de pruebas, nunca en producción con clientes reales.

## Componentes

| Componente | Rol |
|---|---|
| **Evolution API** | Contenedor que mantiene la conexión con WhatsApp (motor Baileys por debajo) y expone una REST API + webhooks para enviar/recibir mensajes. |
| **Postgres** | Persistencia de instancias, chats y mensajes de Evolution API. |
| **Redis** | Cache de estado/eventos que usa Evolution API internamente. |
| **Bridge (FastAPI)** | Traductor entre Evolution API y Monday.com. Expone dos endpoints: `/webhook/evolution` (mensajes entrantes de WhatsApp → los refleja en el board) y `/webhook/monday` (cambios de columna en el board → dispara el envío de WhatsApp). |
| **Caddy** | Reverse proxy con HTTPS automático (Let's Encrypt) delante del bridge — Monday exige que su webhook apunte a una URL HTTPS. |
| **Monday.com board** | Actúa como "base de datos" del POC: un item por contacto, el feed de *updates* como historial de conversación, y columnas dedicadas para escribir y disparar la respuesta. |
| **EC2 + DuckDNS** | Host único (se puede detener/encender sin pagar cómputo) con un subdominio DuckDNS gratuito que se actualiza solo al arrancar la instancia, para que Caddy siempre resuelva a la IP pública vigente. |

## Arquitectura

Todos los servicios corren en un solo `docker-compose.yml`, en la misma red interna de Docker, dentro de una única instancia EC2:

```
                              AWS EC2 (stop/start manual)
                    ┌───────────────────────────────────────────────┐
Monday.com ──HTTPS──▶  Caddy (443) ──▶ Bridge (FastAPI) ──▶ Evolution API ──▶ WhatsApp
  (board)            │                      │                    │
                      │                      │              Postgres + Redis
                      │                      │             (solo red interna)
                      └───────────────────────────────────────────────┘
                                     ▲
                                     │
                    DuckDNS (IP pública actualizada al boot)
```

Flujo de datos:

1. **Entrante**: llega un mensaje de WhatsApp → Evolution API dispara su webhook interno → el bridge busca (o crea) el item correspondiente en el board por número de teléfono → postea el mensaje como *update* en ese item.
2. **Saliente**: alguien escribe una respuesta en la columna "Responder" y activa la columna "Enviar" → Monday dispara su webhook nativo (HTTPS, vía Caddy) → el bridge lee el texto y el teléfono del item → llama a Evolution API para enviar el mensaje por WhatsApp.

Solo Caddy queda expuesto a internet (puertos 80/443). Evolution API, Postgres, Redis y el bridge son alcanzables únicamente dentro de la red interna de Docker; el Manager UI de Evolution API (para escanear el QR) solo es accesible vía túnel SSH.

## Estructura del repo

```
docker-compose.yml     # los 5 servicios
Caddyfile              # reverse proxy + TLS automático
.env.example            # variables a completar (Monday, Evolution, DuckDNS)
bridge/
  main.py               # endpoints /webhook/evolution y /webhook/monday
  requirements.txt
  Dockerfile
infra/
  ec2-user-data.sh      # bootstrap de la instancia: instala Docker + actualiza DuckDNS al arrancar
```

## Requisitos por servicio

| Servicio | Requisitos previos |
|---|---|
| **DuckDNS** | Cuenta gratuita (login con GitHub/Google), un subdominio reservado y su token. |
| **AWS EC2** | Cuenta AWS, permisos para lanzar instancias, un key pair para SSH. Instancia sugerida: `t3.small` (2GB RAM — Postgres + Redis + Evolution API + bridge juntos van justos en `t3.micro`), 20-30GB de disco gp3. |
| **Security Group** | Puertos abiertos: 22 (SSH, restringido a tu IP), 80 y 443 (Caddy). Todo lo demás cerrado. |
| **Monday.com** | Cuenta con permisos para crear boards y un **token API personal** (Avatar → Administration → API). |
| **Número de WhatsApp** | Un número de pruebas (no personal) con WhatsApp activo, para escanear el QR. |
| **Docker / Docker Compose** | Se instalan automáticamente vía `infra/ec2-user-data.sh` en la instancia. Si quieres probar local antes de subir a EC2, necesitas Docker Engine + plugin de Compose en tu máquina. |

## Paso a paso

### 1. Reservar el subdominio en DuckDNS
1. Entra a [duckdns.org](https://www.duckdns.org) y loguéate.
2. Crea un subdominio (ej. `mi-poc-whatsapp`) y copia tu **token**.
3. No hace falta apuntar la IP todavía — se actualiza sola cuando arranque la instancia.

### 2. Crear el board en Monday.com
1. Crea un board nuevo con las columnas: **Teléfono** (texto), **Responder** (texto), **Enviar** (status o checkbox).
2. Anota el `board_id` (aparece en la URL del board).
3. Anota el ID de cada columna (Configuración de la columna → "..." → suele mostrarse como *Column ID*, o vía la API con `query { boards(ids: [BOARD_ID]) { columns { id title } } }`).
4. Genera tu token API personal (Avatar → Administration → API).

### 3. Lanzar la instancia EC2
1. AMI: Amazon Linux 2023 o Ubuntu 22.04. Tipo: `t3.small`.
2. Security Group con los puertos del punto anterior.
3. Antes de lanzarla, abre `infra/ec2-user-data.sh` y reemplaza `__DUCKDNS_SUBDOMAIN__` y `__DUCKDNS_TOKEN__` con tus valores reales.
4. Pega el script editado en el campo *User data* al lanzar la instancia.
5. Lanza la instancia y espera 1-2 min a que corra el bootstrap (instala Docker y arranca el servicio de actualización de DuckDNS).

### 4. Copiar el proyecto al servidor
```bash
scp -r ./* usuario@<ip-o-dominio>:/opt/whatsapp-monday
ssh usuario@<ip-o-dominio>
```

### 5. Completar las variables de entorno
```bash
cd /opt/whatsapp-monday
cp .env.example .env
```
Rellena en `.env`:
- `DOMAIN` → tu dominio DuckDNS completo (ej. `mi-poc-whatsapp.duckdns.org`)
- `EVOLUTION_API_KEY` → inventa una clave larga y aleatoria
- `EVOLUTION_INSTANCE` → nombre libre para tu instancia de WhatsApp (ej. `poc-whatsapp`)
- `POSTGRES_PASSWORD` → contraseña nueva
- `MONDAY_API_TOKEN`, `MONDAY_BOARD_ID`, `MONDAY_PHONE_COLUMN_ID`, `MONDAY_REPLY_COLUMN_ID`, `MONDAY_SEND_COLUMN_ID` → los datos del paso 2

### 6. Levantar los contenedores
```bash
docker compose up -d --build
docker compose ps
```

### 7. Crear la instancia de WhatsApp y escanear el QR
1. Desde tu máquina local, abre un túnel SSH al Manager UI (que solo escucha en loopback del servidor):
   ```bash
   ssh -L 8080:localhost:8080 usuario@<ip-o-dominio>
   ```
2. Abre `http://localhost:8080` en tu navegador, autentícate con `EVOLUTION_API_KEY`.
3. Crea una instancia con el mismo nombre que pusiste en `EVOLUTION_INSTANCE`.
4. Escanea el QR con el número de pruebas.

### 8. Configurar el webhook nativo de Monday
1. En el board: Integraciones → Webhooks → "Cuando cambie una columna" → selecciona la columna **Enviar**.
2. URL destino: `https://<tu-dominio-duckdns>/webhook/monday`.
3. Monday manda un `challenge` de verificación al guardar — el bridge ya lo responde automáticamente.

### 9. Probar end-to-end
1. Manda un WhatsApp al número de pruebas desde tu celular → debe aparecer un item nuevo (o un *update*) en el board.
2. Escribe algo en la columna **Responder** y activa **Enviar** → debe llegar el mensaje al WhatsApp de origen.

### 10. Apagar cuando no lo uses
```bash
aws ec2 stop-instances --instance-ids <id-de-tu-instancia>
```
Al volver a prenderla, el servicio `duckdns-update` corre solo y actualiza el DNS con la IP nueva — solo espera 1-2 min antes de volver a probar.
