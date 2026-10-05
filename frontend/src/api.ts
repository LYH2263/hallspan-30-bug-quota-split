export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message)
  }
}

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch('/api' + path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!res.ok) {
    let message = res.statusText
    let code = 'error'
    try {
      const body = await res.json()
      if (body && typeof body === 'object') {
        // FastAPI HTTPException(detail={code, detail}) -> { detail: { code, detail } }
        const d = body.detail
        if (d && typeof d === 'object') {
          code = d.code ?? code
          message = d.detail ?? message
        } else {
          message = typeof d === 'string' ? d : message
        }
      } else {
        message = String(body)
      }
    } catch { /* keep statusText */ }
    throw new ApiError(res.status, code, message)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}
