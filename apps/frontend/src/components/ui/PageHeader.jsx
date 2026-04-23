const PageHeader = ({ title, icon: Icon, description, actions, className }) => (
  <div className={`flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6 ${className || ''}`}>
    <div className="flex items-center gap-3">
      {Icon && (
        <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
          <Icon className="h-5 w-5 text-primary" />
        </div>
      )}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        {description && (
          <p className="text-sm text-muted-foreground mt-0.5">{description}</p>
        )}
      </div>
    </div>
    {actions && (
      <div className="flex gap-2 flex-shrink-0">
        {actions}
      </div>
    )}
  </div>
);

export default PageHeader;
