// API Services
export { generateResponse as generateNaasResponse } from './services/naasService.js';
export { generateResponse as generateGeminiResponse } from './services/geminiService.js';

// Re-export the main service for backward compatibility
export { generateResponse } from './services/naasService.js'; 