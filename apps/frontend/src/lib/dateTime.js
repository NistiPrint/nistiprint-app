export const APP_TIME_ZONE = 'America/Sao_Paulo';
export const APP_LOCALE = 'pt-BR';
const DATE_ONLY_RE = /^\d{4}-\d{2}-\d{2}$/;

function parseDate(value) {
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(value);
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
