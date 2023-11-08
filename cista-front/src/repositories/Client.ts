class ClientClass {
  async post(url: string, data?: Record<string, any>): Promise<any> {
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        accept: 'application/json',
        'content-type': 'application/json'
      },
      body: data !== undefined ? JSON.stringify(data) : undefined
    })
    let msg
    try {
      msg = await res.json()
    } catch (e) {
      throw new SimpleError(res.status, `🛑 ${res.status} ${res.statusText}`)
    }
    if ('error' in msg) throw new SimpleError(msg.error.code, msg.error.message)
    return msg
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

export default Client
