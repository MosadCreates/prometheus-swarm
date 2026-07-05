export const promptSuggestions = [
  'Build a classification model for my dataset',
  'Analyze customer churn patterns',
  'Train an object detector on images',
  'Generate model documentation',
  'Optimize hyperparameters',
  'Create a deployment pipeline',
];

export const promptTemplates = [
  { category: 'Machine Learning', prompts: ['Train a binary classifier', 'Build a regression model', 'Run feature selection'] },
  { category: 'Deep Learning', prompts: ['Fine-tune a transformer', 'Train a CNN', 'Build an LSTM for time series'] },
  { category: 'Data Analysis', prompts: ['Perform EDA on dataset', 'Generate statistical report', 'Detect anomalies'] },
  { category: 'Computer Vision', prompts: ['Train image classifier', 'Build object detection', 'Segment images'] },
  { category: 'NLP', prompts: ['Sentiment analysis pipeline', 'Text summarization', 'Named entity recognition'] },
];

export const mockProjectContext = {
  name: 'Kaggle Titanic',
  files: ['titanic.csv', 'train.py', 'features.py', 'README.md'],
  datasets: ['titanic_train.csv', 'titanic_test.csv'],
  previousMissions: ['EDA pipeline', 'Baseline model', 'Feature engineering'],
  recentModels: ['LightGBM v1', 'XGBoost v2'],
};

export const executionModes = [
  { value: 'fast', label: 'Fast', desc: 'Quick experiment, minimal tuning' },
  { value: 'balanced', label: 'Balanced', desc: 'Standard quality with moderate tuning' },
  { value: 'quality', label: 'Maximum Quality', desc: 'Extensive search for best performance' },
];

export const priorities = [
  { value: 'low', label: 'Low' },
  { value: 'normal', label: 'Normal' },
  { value: 'high', label: 'High' },
  { value: 'critical', label: 'Critical' },
];

export const outputOptions = [
  { value: 'code', label: 'Code' },
  { value: 'model', label: 'Model' },
  { value: 'documentation', label: 'Documentation' },
  { value: 'report', label: 'Report' },
  { value: 'dataset', label: 'Dataset' },
  { value: 'deployment', label: 'Deployment Package' },
];

export const resourcePresets = [
  { value: 'small', label: 'Small', cpu: '2 vCPU', memory: '8 GB', storage: '20 GB' },
  { value: 'medium', label: 'Medium', cpu: '4 vCPU', memory: '16 GB', storage: '50 GB' },
  { value: 'large', label: 'Large', cpu: '8 vCPU', memory: '32 GB', storage: '100 GB' },
];
