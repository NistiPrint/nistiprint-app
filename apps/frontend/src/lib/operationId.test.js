import test from 'node:test'
import assert from 'node:assert/strict'
import { createOperationId } from './operationId.js'

test('createOperationId returns an RFC 4122 version 4 UUID', () => {
  assert.match(createOperationId(), /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
})
