export const APP_TIME_ZONE = 'America/Sao_Paulo';
export const APP_LOCALE = 'pt-BR';
const DATE_ONLY_RE = /^\d{4}-\d{2}-\d{2}$/;
const BR_DATE_RE = /^(\d{2})\/(\d{2})\/(\d{4})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?$/;
const NUMERIC_RE = /^\d+$/;

function normalizeDateString(value) {
  if (typeof value !== 'string') return value;

  let normalized = value.trim();
  if (!normalized) return normalized;

  const brDate = normalized.match(BR_DATE_RE);
  if (brDate) {
    const [, day, month, year, hour = '00', minute = '00', second = '00'] = brDate;
    return `${year}-${month}-${day}T${hour}:${minute}:${second}-03:00`;
  }

  if (NUMERIC_RE.test(normalized)) {
    const timestamp = Number(normalized);
    return timestamp < 10000000000 ? timestamp * 1000 : timestamp;
  }

  if (DATE_ONLY_RE.test(normalized)) {
    return `${normalized}T00:00:00-03:00`;
  }

  normalized = normalized.replace(' ', 'T');
  normalized = normalized.replace(/([+-]\d{2})(\d{2})$/, '$1:$2');
  normalized = normalized.replace(/([+-]\d{2})$/, '$1:00');
  return normalized;
}

function parseDate(value) {
  if (!value) return null;
  if (typeof value === 'number') {
    const timestamp = value < 10000000000 ? value * 1000 : value;
    const date = new Date(timestamp);
    return Number.isNaN(date.getTime()) ? null : date;
  }
  const normalized = normalizeDateString(value);
  const date = normalized instanceof Date ? normalized : new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatDateOnly(value) {
  const [year, month, day] = value.split('-');
  return `${day}/${month}/${year}`;
}

export function formatAppDate(value, options = {}) {
  if (typeof value === 'string' && DATE_ONLY_RE.test(value)) {
    return formatDateOnly(value);
  }

  const date = parseDate(value);
  const { fallback = '-', ...formatOptions } = options;
  if (!date) return fallback;

  return new Intl.DateTimeFormat(APP_LOCALE, {
    timeZone: APP_TIME_ZONE,
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    ...formatOptions,
  }).format(date);
}

export function formatAppDateTime(value, options = {}) {
  const date = parseDate(value);
  const { fallback = '-', ...formatOptions } = options;
  if (!date) return fallback;

  return new Intl.DateTimeFormat(APP_LOCALE, {
    timeZone: APP_TIME_ZONE,
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    ...formatOptions,
  }).format(date);
}

export function formatAppDateInput(value = new Date()) {
  if (typeof value === 'string' && DATE_ONLY_RE.test(value)) {
    return value;
  }

  const date = parseDate(value);
  if (!date) return '';

  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: APP_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(date);

  const byType = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${byType.year}-${byType.month}-${byType.day}`;
}
