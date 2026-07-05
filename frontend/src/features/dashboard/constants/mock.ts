export const mockMetrics = [
  { label: 'Active Projects', value: 12, change: '+2' },
  { label: 'Running Missions', value: 3, change: '+1' },
  { label: 'Trained Models', value: 28, change: '+5' },
  { label: 'Datasets', value: 15, change: '+3' },
];

export const mockQuickActions = [
  { label: 'New Mission', href: '/missions', icon: 'Rocket' as const },
  { label: 'Create Project', href: '/projects', icon: 'FolderKanban' as const },
  { label: 'Upload Dataset', href: '/datasets', icon: 'Upload' as const },
  { label: 'View Models', href: '/models', icon: 'Brain' as const },
  { label: 'Training Runs', href: '/training', icon: 'GraduationCap' as const },
  { label: 'Deployments', href: '/deployments', icon: 'Globe' as const },
];

export const mockProjects = [
  { id: '1', name: 'Kaggle Titanic', description: 'Binary classification survival prediction', lastUpdated: '2h ago', status: 'active' as const, missions: 5, color: '#2563eb' },
  { id: '2', name: 'NLP Sentiment Pipeline', description: 'Multi-class sentiment analysis on reviews', lastUpdated: '1d ago', status: 'active' as const, missions: 3, color: '#7c3aed' },
  { id: '3', name: 'Vision Demo', description: 'Image classification with EfficientNet', lastUpdated: '3d ago', status: 'completed' as const, missions: 2, color: '#059669' },
  { id: '4', name: 'Fraud Detection', description: 'Anomaly detection on transaction data', lastUpdated: '5d ago', status: 'draft' as const, missions: 1, color: '#d97706' },
];

export const mockMissions = [
  { id: '1', name: 'Titanic EDA + Training', status: 'running' as const, progress: 65, agents: ['Scout', 'Forge', 'Furnace'], started: '10:32 AM', eta: '~12 min' },
  { id: '2', name: 'Sentiment Baseline', status: 'queued' as const, progress: 0, agents: ['Scout'], started: '—', eta: '—' },
  { id: '3', name: 'Feature Engineering Pipeline', status: 'completed' as const, progress: 100, agents: ['Scout', 'Forge'], started: '9:15 AM', eta: 'Done' },
  { id: '4', name: 'Hyperparameter Tuning', status: 'failed' as const, progress: 34, agents: ['Scout', 'Forge', 'Furnace', 'Dissect'], started: '11:00 AM', eta: 'Failed' },
];

export const mockActivity = [
  { id: '1', type: 'mission' as const, title: 'Titanic EDA + Training', description: 'Mission completed successfully', time: '2m ago' },
  { id: '2', type: 'model' as const, title: 'LightGBM v3', description: 'Model trained with AUC 0.89', time: '15m ago' },
  { id: '3', type: 'dataset' as const, title: 'titanic.csv', description: 'Dataset uploaded to workspace', time: '1h ago' },
  { id: '4', type: 'deployment' as const, title: 'Fraud API v2', description: 'Deployed to production endpoint', time: '3h ago' },
  { id: '5', type: 'project' as const, title: 'Kaggle Titanic', description: 'Project updated with new mission', time: '5h ago' },
  { id: '6', type: 'mission' as const, title: 'Feature Engineering', description: 'Dissect patched a ValueError', time: '1d ago' },
];

export const mockResources = [
  { id: '1', name: 'Getting Started Guide', type: 'doc' as const },
  { id: '2', name: 'API Reference', type: 'doc' as const },
  { id: '3', name: 'Titanic Dataset', type: 'dataset' as const },
  { id: '4', name: 'LightGBM v3', type: 'model' as const },
];

export const projectStatusStyles: Record<string, string> = {
  active: 'bg-[var(--color-primary)]/10 text-[var(--color-primary)]',
  completed: 'bg-[var(--color-success)]/10 text-[var(--color-success)]',
  draft: 'bg-[var(--color-warning)]/10 text-[var(--color-warning)]',
  archived: 'bg-[var(--color-text-muted)]/10 text-[var(--color-text-muted)]',
};

export const missionStatusStyles: Record<string, string> = {
  running: 'bg-[var(--color-primary)]/10 text-[var(--color-primary)]',
  queued: 'bg-[var(--color-text-muted)]/10 text-[var(--color-text-muted)]',
  completed: 'bg-[var(--color-success)]/10 text-[var(--color-success)]',
  failed: 'bg-[var(--color-error)]/10 text-[var(--color-error)]',
};
