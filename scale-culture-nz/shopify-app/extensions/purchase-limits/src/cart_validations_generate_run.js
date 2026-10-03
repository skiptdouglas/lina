// @ts-check
import { limitErrors } from './limits.js';

/**
 * @param {any} input CartValidationsGenerateRunInput
 * @returns {{ operations: Array<{ validationAdd: { errors: Array<{ message: string, target: string }> } }> }}
 */
export function cartValidationsGenerateRun(input) {
  const errors = limitErrors(input).map((message) => ({ message, target: '$.cart' }));
  return { operations: errors.length ? [{ validationAdd: { errors } }] : [] };
}
