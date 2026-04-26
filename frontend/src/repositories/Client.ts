import { AuthCancelledError, apiFetch, apiJson } from 'paskia'

// Type for API error responses
interface ApiError {
  error: {
    code: number
    message: string
  }
}

function hasError(msg: unknown): msg is ApiError {
  return typeof msg === 'object' && msg !== null && 'error' in msg
}

class ClientClass {
  async get(url: string): Promise<any> {
    try {
      const msg = await apiJson(url, { method: 'GET' })
      if (hasError(msg)) throw new SimpleError(msg.error.code, msg.error.message)
      return msg
    } catch (e) {
      if (e instanceof AuthCancelledError) {
        throw new SimpleError(401, 'Authentication cancelled')
      }
      throw e
    }
  }
  async post(url: string, data?: Record<string, any>): Promise<any> {
    try {
      const msg = await apiJson(url, {
        method: 'POST',
        body: data
      })
      if (hasError(msg)) throw new SimpleError(msg.error.code, msg.error.message)
      return msg
    } catch (e) {
      if (e instanceof AuthCancelledError) {
        throw new SimpleError(401, 'Authentication cancelled')
      }
      throw e
    }
  }
  async put(url: string, data?: Record<string, any>): Promise<any> {
    try {
      const msg = await apiJson(url, {
        method: 'PUT',
        body: data
      })
      if (hasError(msg)) throw new SimpleError(msg.error.code, msg.error.message)
      return msg
    } catch (e) {
      if (e instanceof AuthCancelledError) {
        throw new SimpleError(401, 'Authentication cancelled')
      }
      throw e
    }
  }
  async delete(url: string): Promise<any> {
    try {
      const msg = await apiJson(url, { method: 'DELETE' })
      if (hasError(msg)) throw new SimpleError(msg.error.code, msg.error.message)
      return msg
    } catch (e) {
      if (e instanceof AuthCancelledError) {
        throw new SimpleError(401, 'Authentication cancelled')
      }
      throw e
    }
  }
}

export const Client = new ClientClass()
export interface ISimpleError extends Error {
  code: number
}

class SimpleError extends Error implements ISimpleError {
  code: number
  constructor(code: number, message: string) {
    super(message)
    this.code = code
  }
}

export { apiFetch }
export default Client
