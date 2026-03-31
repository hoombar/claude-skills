# Evidence Log Format

The generator agent MUST produce an evidence log alongside every mermaid diagram generated from code. This log forces the generator to show its working and enables the critic to verify claims.

## Structure

### 1. Diagram Metadata

```markdown
- **Type**: flowchart | sequence | classDiagram | stateDiagram | erDiagram
- **Scope**: [user's original request, verbatim]
- **Entry points explored**: [list of starting files/functions]
```

### 2. Entity Evidence Table

Every node, participant, class, state, or entity in the diagram must have an entry.

| Diagram Node | Code Entity | File | Line | Description |
|---|---|---|---|---|
| `AuthService` | `class AuthService` | `src/auth/service.ts` | 12 | Handles token validation and refresh |

### 3. Relationship Evidence Table

Every arrow, edge, message, or connection in the diagram must have an entry.

| From | To | Relationship | Source File:Line | Confidence |
|---|---|---|---|---|
| `AuthService` | `TokenStore` | calls `tokenStore.get()` | `src/auth/service.ts:45` | High |
| `AuthService` | `AuditLog` | emits `auth.validated` event | `src/auth/service.ts:52` | High |
| `Gateway` | `RateLimiter` | inferred from middleware chain | `src/gateway/index.ts:18` | Medium |

**Confidence levels:**
- **High** — direct call site, import statement, or explicit reference in code
- **Medium** — inferred from patterns (middleware chains, event registrations, DI containers)
- **Low** — assumed from naming conventions, project structure, or documentation only

### 4. Deliberate Omissions

List components or relationships that exist in the code but were intentionally excluded from the diagram.

| Omitted Entity/Relationship | Reason |
|---|---|
| `LoggingMiddleware` | Orthogonal to the auth flow; would add noise without insight |
| `HealthCheck → AuthService` | Health check dependency is operational, not part of the auth domain |

### 5. Assumptions

Inferences not directly supported by the explorer output or code reading.

| Assumption | Basis |
|---|---|
| `UserService` is called after auth succeeds | Function ordering in handler, not explicit control flow |

---

## Worked Example: Sequence Diagram

For a request like "show me the login flow":

```markdown
- **Type**: sequence
- **Scope**: Login flow from HTTP request to token issuance
- **Entry points explored**: src/routes/auth.ts, src/auth/loginHandler.ts
```

| Diagram Node | Code Entity | File | Line | Description |
|---|---|---|---|---|
| `Client` | (external actor) | — | — | HTTP caller |
| `AuthRoute` | `router.post('/login')` | `src/routes/auth.ts` | 8 | Route handler |
| `LoginHandler` | `async function handleLogin()` | `src/auth/loginHandler.ts` | 15 | Orchestrates login |
| `UserRepo` | `class UserRepository` | `src/db/userRepo.ts` | 3 | Database access |
| `TokenService` | `class TokenService` | `src/auth/tokenService.ts` | 7 | JWT generation |

| From | To | Relationship | Source File:Line | Confidence |
|---|---|---|---|---|
| `AuthRoute` | `LoginHandler` | calls `handleLogin(req, res)` | `src/routes/auth.ts:10` | High |
| `LoginHandler` | `UserRepo` | calls `userRepo.findByEmail(email)` | `src/auth/loginHandler.ts:22` | High |
| `LoginHandler` | `TokenService` | calls `tokenService.sign(user)` | `src/auth/loginHandler.ts:30` | High |
| `TokenService` | `LoginHandler` | returns `{ accessToken, refreshToken }` | `src/auth/tokenService.ts:45` | High |

## Worked Example: Flowchart

For a request like "show me the request validation pipeline":

```markdown
- **Type**: flowchart
- **Scope**: Request validation from middleware entry to handler dispatch
- **Entry points explored**: src/middleware/validate.ts, src/middleware/index.ts
```

| Diagram Node | Code Entity | File | Line | Description |
|---|---|---|---|---|
| `Request In` | `app.use(validateRequest)` | `src/middleware/index.ts` | 12 | Middleware entry |
| `Schema Check` | `if (!schema.validate(req.body))` | `src/middleware/validate.ts` | 18 | JSON schema validation |
| `Auth Check` | `if (!req.headers.authorization)` | `src/middleware/validate.ts` | 25 | Token presence check |
| `400 Response` | `res.status(400).json(errors)` | `src/middleware/validate.ts` | 20 | Validation failure |
| `401 Response` | `res.status(401).json(...)` | `src/middleware/validate.ts` | 27 | Auth failure |
| `Next Handler` | `next()` | `src/middleware/validate.ts` | 32 | Pass to route handler |

| From | To | Relationship | Source File:Line | Confidence |
|---|---|---|---|---|
| `Request In` | `Schema Check` | sequential middleware | `src/middleware/index.ts:12` | High |
| `Schema Check` | `400 Response` | validation fails branch | `src/middleware/validate.ts:19` | High |
| `Schema Check` | `Auth Check` | validation passes | `src/middleware/validate.ts:24` | High |
| `Auth Check` | `401 Response` | no auth header | `src/middleware/validate.ts:26` | High |
| `Auth Check` | `Next Handler` | auth present | `src/middleware/validate.ts:32` | High |
