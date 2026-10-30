export function productImages(product) {
  const values = product?.atributos?.images;
  if (!Array.isArray(values)) return [];
  return [...new Set(values.flatMap((image) => {
    const value = typeof image === 'string' ? image : image?.url;
    try {
      const url = new URL(value);
      return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? [url.href] : [];
    } catch {
      return [];
    }
  }))];
}
