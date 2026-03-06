import { useState, useEffect } from 'react';
import LocalAgentService from '../services/LocalAgentService';

const useLocalAgent = () => {
  const [isAgentOnline, setIsAgentOnline] = useState(false);
  const [checkingAgent, setCheckingAgent] = useState(true);

  // Function to check if the local agent is online
  const checkAgentStatus = async () => {
    try {
      await LocalAgentService.checkHealth();
      setIsAgentOnline(true);
    } catch (error) {
      setIsAgentOnline(false);
    } finally {
      setCheckingAgent(false);
    }
  };

  // Check agent status on mount and periodically
  useEffect(() => {
    // Check immediately
    checkAgentStatus();

    // Then check every 10 seconds
    const interval = setInterval(checkAgentStatus, 10000);

    return () => {
      clearInterval(interval);
    };
  }, []);

  // Function to map a file to a product ID
  const mapFileToProduct = async (productId) => {
    if (!isAgentOnline) {
      throw new Error('Local agent is not running. Please start the local agent service.');
    }

    try {
      const result = await LocalAgentService.mapFile(productId);
      // After mapping, we might want to refresh the status
      setTimeout(checkAgentStatus, 1000); // Small delay to allow for file selection
      return result;
    } catch (error) {
      console.error('Error mapping file to product:', error);
      throw error;
    }
  };

  // Function to print a mapped file
  const printMappedFile = async (productId, copies = 1) => {
    if (!isAgentOnline) {
      throw new Error('Local agent is not running. Please start the local agent service.');
    }

    try {
      const result = await LocalAgentService.printFile(productId, copies);
      return result;
    } catch (error) {
      console.error('Error printing mapped file:', error);
      throw error;
    }
  };

  // Function to get the mapped file for a product
  const getMappedFileForProduct = async (productId) => {
    if (!isAgentOnline) {
      // Even if agent is offline, we return null rather than throwing
      // to allow UI to handle gracefully
      return null;
    }

    try {
      const result = await LocalAgentService.getMappedFile(productId);
      return result;
    } catch (error) {
      // If the product isn't mapped, the agent returns a 404, which is expected
      if (error.response?.status === 404) {
        return null;
      }
      console.error('Error getting mapped file for product:', error);
      throw error;
    }
  };

  return {
    isAgentOnline,
    checkingAgent,
    checkAgentStatus,
    mapFileToProduct,
    printMappedFile,
    getMappedFileForProduct
  };
};

export default useLocalAgent;