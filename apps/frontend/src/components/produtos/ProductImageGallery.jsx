import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { productImages } from '@/lib/productImages';

function RemoteImage({ src, alt, className }) {
  const [failed, setFailed] = useState(false);
  return failed ? (
    <span className={`${className} grid place-items-center bg-muted text-xs text-muted-foreground`}>Imagem indisponível</span>
  ) : (
    <img src={src} alt={alt} className={className} loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
  );
}

export default function ProductImageGallery({ product }) {
  const images = productImages(product);
  const [selected, setSelected] = useState(null);
  if (!images.length) return null;
  const primary = images.includes(selected) ? selected : images[0];
  return (
    <Card className="mb-6">
      <CardHeader><CardTitle>Imagens do produto</CardTitle></CardHeader>
      <CardContent>
        <a href={primary} target="_blank" rel="noopener noreferrer" className="block w-fit" aria-label="Abrir imagem do produto">
          <RemoteImage key={primary} src={primary} alt={product.name || product.nome || 'Produto'} className="h-72 w-72 rounded-md border object-contain" />
        </a>
        {images.length > 1 && <div className="mt-3 flex flex-wrap gap-2">
          {images.map((url, index) => <button key={url} type="button" onClick={() => setSelected(url)} aria-label={`Ver imagem ${index + 1}`} aria-pressed={url === primary} className={`rounded-md border-2 ${url === primary ? 'border-primary' : 'border-transparent'}`}>
            <RemoteImage src={url} alt={`Imagem ${index + 1}`} className="h-16 w-16 rounded object-contain" />
          </button>)}
        </div>}
        <p className="mt-3 text-sm text-muted-foreground">Imagens dos anúncios vinculados. A disponibilidade depende da plataforma de origem.</p>
      </CardContent>
    </Card>
  );
}
