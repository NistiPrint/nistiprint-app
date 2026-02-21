import { useState, useEffect, useRef } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Trash2, Upload, FileText, Eye, Printer } from 'lucide-react';
import { toast } from 'sonner';
import ProductService from '@/services/ProductService';
import PrintService from '@/services/PrintService';

const ArtworkManager = ({ productId }) => {
  const [artworks, setArtworks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef(null);

  // Load artworks when component mounts or productId changes
  useEffect(() => {
    if (productId) {
      loadArtworks();
    }
  }, [productId]);

  const loadArtworks = async () => {
    try {
      setLoading(true);
      const response = await ProductService.getArtworks(productId);
      setArtworks(response.artworks || []);
    } catch (error) {
      console.error('Error loading artworks:', error);
      toast.error(`Erro ao carregar artes: ${error.response?.data?.error || error.message}`);
      setArtworks([]);
    } finally {
      setLoading(false);
    }
  };

  const handleSendToPrint = async (artworkId) => {
    if (!productId) {
      toast.error('Produto não identificado');
      return;
    }

    try {
      const response = await PrintService.sendToPrint(productId, artworkId);
      if (response.success) {
        toast.success(response.message);
      } else {
        throw new Error(response.message || 'Erro desconhecido');
      }
    } catch (error) {
      console.error('Error sending to print:', error);
      toast.error(`Erro ao enviar para impressão: ${error.response?.data?.error || error.message}`);
    }
  };

  const handleFileChange = async (event) => {
    const file = event.target.files[0];
    if (!file) return;

    // Validate file type
    const allowedTypes = ['image/png', 'image/jpeg', 'image/jpg', 'image/gif', 'application/pdf'];
    if (!allowedTypes.includes(file.type)) {
      toast.error('Tipo de arquivo não suportado. Permitidos: PNG, JPG, JPEG, GIF, PDF');
      return;
    }

    // Validate file size (max 10MB)
    const maxSize = 10 * 1024 * 1024; // 10MB in bytes
    if (file.size > maxSize) {
      toast.error('Arquivo muito grande. Tamanho máximo: 10MB');
      return;
    }

    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('artwork', file);

      const response = await ProductService.uploadArtwork(productId, formData);
      
      if (response.success) {
        toast.success('Arte enviada com sucesso!');
        // Refresh artworks list
        const artworksResponse = await ProductService.getArtworks(productId);
        setArtworks(artworksResponse.artworks || []);
      } else {
        throw new Error(response.message || 'Erro ao enviar arte');
      }
    } catch (error) {
      console.error('Error uploading artwork:', error);
      toast.error(`Erro ao enviar arte: ${error.response?.data?.error || error.message}`);
    } finally {
      setUploading(false);
      // Reset file input
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleDeleteArtwork = async (artworkId) => {
    if (!window.confirm('Tem certeza que deseja excluir esta arte?')) {
      return;
    }

    try {
      await ProductService.deleteArtwork(artworkId);
      toast.success('Arte excluída com sucesso!');
      // Refresh artworks list
      const artworksResponse = await ProductService.getArtworks(productId);
      setArtworks(artworksResponse.artworks || []);
    } catch (error) {
      console.error('Error deleting artwork:', error);
      toast.error(`Erro ao excluir arte: ${error.response?.data?.error || error.message}`);
    }
  };

  const handleDownloadArtwork = (artwork) => {
    // Create a temporary link to download the file
    const link = document.createElement('a');
    link.href = artwork.file_path;
    link.download = artwork.original_filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleViewArtwork = async (artwork) => {
    // Request a secure signed URL from the backend
    try {
      const response = await fetch(`/api/v2/produtos/artwork/${artwork.id}/view`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          // Include any authentication headers if required by your app
          // 'Authorization': `Bearer ${localStorage.getItem('token')}`, // example
        },
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to get artwork URL');
      }

      const data = await response.json();

      // Check if signed_url exists
      if (!data.signed_url) {
        throw new Error('No signed URL received from server');
      }

      // Open the signed URL in a new tab/window for viewing
      window.open(data.signed_url, '_blank');
    } catch (error) {
      console.error('Error getting artwork URL:', error);
      toast.error(`Erro ao acessar a arte: ${error.message}`);
    }
  };

  const getFileIcon = (mimeType) => {
    if (mimeType?.includes('image')) {
      return <FileText className="h-8 w-8 text-blue-500" />;
    } else if (mimeType?.includes('pdf')) {
      return <FileText className="h-8 w-8 text-red-500" />;
    }
    return <FileText className="h-8 w-8 text-gray-500" />;
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex justify-between items-center">
          <span>Artes do Produto</span>
          <div className="flex items-center gap-2">
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileChange}
              accept=".png,.jpg,.jpeg,.gif,.pdf"
              className="hidden"
            />
            <Button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              size="sm"
            >
              {uploading ? (
                <>
                  <Upload className="mr-2 h-4 w-4 animate-spin" />
                  Enviando...
                </>
              ) : (
                <>
                  <Upload className="mr-2 h-4 w-4" />
                  Enviar Arte
                </>
              )}
            </Button>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {artworks.length === 0 ? (
          <p className="text-muted-foreground text-center py-4">
            Nenhuma arte cadastrada para este produto.
          </p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {artworks.map((artwork) => (
              <div
                key={artwork.id}
                className="border rounded-lg p-3 flex flex-col items-center bg-card"
              >
                <div className="mb-2">{getFileIcon(artwork.mime_type)}</div>
                <div className="text-sm font-medium text-center truncate w-full">
                  {artwork.original_filename}
                </div>
                <div className="text-xs text-muted-foreground mb-2">
                  {(artwork.file_size / 1024).toFixed(2)} KB
                </div>
                <div className="flex gap-2 mt-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleViewArtwork(artwork)}
                    title="Visualizar"
                  >
                    <Eye className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleSendToPrint(artwork.id)}
                    title="Imprimir"
                  >
                    <Printer className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleDeleteArtwork(artwork.id)}
                    title="Excluir"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
};

export default ArtworkManager;