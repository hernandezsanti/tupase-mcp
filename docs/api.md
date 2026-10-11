# Endpoints de Tupase que usa este cliente

Base: `https://production.api.tupaseapp.com/`
Auth: `Authorization: Bearer <access_token>` de Auth0 (grant password-realm).
Referencia informal de los endpoints que consume `tupase-mcp`; no es documentación oficial de Tupase y puede cambiar sin aviso.

Leyenda: ✅ verificado con una cuenta real · 👀 sin verificar todavía

## Búsqueda (lo que necesita "ver lugares / filtrar")

| | Método y ruta | Body |
|---|---|---|
| ✅ | POST `search/activities/search-by-location` | latitude, longitude, distance, startDateTimeFrom, startDateTimeTo, disciplineGroups[], entityIds[], zoneIds[] |
| 👀 | POST `search/disciplines/search-by-location` | latitude, longitude, distance, startDateTimeFrom, startDateTimeTo, disciplineNames[], entityIds[] |
| 👀 | POST `search/neighbourhoods/search-by-location` | startDateTimeFrom, startDateTimeTo |

`zoneIds` (barrios) y `entityIds` (lugares) permiten filtrar del lado del servidor.

## Reservas

| | Método y ruta | Body / params |
|---|---|---|
| ✅ | GET `users/reservations/user/{userId}` | query: page, pageSize |
| ✅ | POST `users/reservations` | activityDate, activityId, activityName, entityId, timeStamp, userLogicalId |
| ✅ | POST `users/reservations/cancel` | activityDateStr, reservationIdentityId (`activityDateStr` son los primeros 10 caracteres del inicio en UTC) |
| 👀 | POST `users/reservations/cancel` (variante) | activityId, userLogicalId |

## Cuenta y notificaciones

| | Método y ruta | Notas |
|---|---|---|
| ✅ | GET `users/notifications` | query: limit, page |
| 👀 | GET `users/user-account/{userLogicalId}` | perfil |
| 👀 | GET `users/user-account/status/{userLogicalId}` | si la cuenta está activa/válida |
| 👀 | GET `countries` | catálogo |
| 👀 | PUT `users/user-account` | editar perfil (escritura, fuera de alcance) |
| 👀 | POST `users/user-account` | alta de usuario (fuera de alcance) |
| 👀 | POST `users/notifications/player` | registro de push (fuera de alcance) |
| 👀 | GET `payment-preferences/user/{userLogicalId}` | pagos MercadoPago (fuera de alcance) |

## Verificado con una cuenta real (2026-10-11)

- **Ventana de búsqueda:** `startDateTimeFrom`/`To` se interpretan en UTC; una ventana de 18:00 a 19:00 locales devuelve actividades de esas horas (el extremo final es inclusivo). En hora pico una ventana de 30 minutos ya devuelve el tope de 499 resultados; el cliente completa la hora partiendo además por `disciplineGroups` (a las 18:00, 899 actividades en unos 45 pedidos).
- **`entityIds`:** el filtro se aplica en el servidor.
- **Reservas del usuario:** vienen de la más nueva a la más vieja; `pageSize=9999` no se recorta. Los estados vistos son `CONFIRMED`, `PENDING_CONFIRMATION` y `CANCELLED`.
- **QR:** `qrUri` es un PNG público (sin autenticación) alojado en S3.
- **Disciplinas:** `[{discipline, quantity}]`. **Barrios:** `[{city, country, zone, zoneId}]` (el `zoneId` es un entero que acepta `zoneIds` en la búsqueda).
- **Medios de pago:** `GET payment-preferences/user/{id}` respondió 500 para la cuenta de prueba.
- **Crear reserva:** `POST users/reservations` responde la reserva (`reservationIdentityCode`, `status`, `statusStr`, `qrUri`, `activityInfo`). Un gimnasio de sala de musculación queda en `PENDING_CONFIRMATION`.
- **Cancelar:** `POST users/reservations/cancel` con `activityDateStr` (`YYYY-MM-DD`, primeros 10 caracteres de la fecha UTC de inicio) y `reservationIdentityId`; responde la reserva con `status: CANCELLED` y `statusStr` vacío.
- **Editar perfil:** `PUT users/user-account` con el objeto completo (`activationCode`, `birthDate`, `countryId`, `deviceIdentifier`, `email`, `firstName`, `lastName`, `phone`, `userDocument`, `userLogicalId`) responde `true`; reenviar los mismos valores no cambia nada.

## Pendiente de verificar

- Qué fecha espera la cancelación para una clase que empieza a las 21:00 locales o más tarde (su fecha UTC es el día siguiente). Los gimnasios probados empiezan como máximo a las 20:30.
