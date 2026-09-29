const PageHeader = ({ title, icon: Icon, description, actions, className }) => (
  <header className={`mb-6 flex flex-col gap-4 border-b border-border/80 pb-5 sm:flex-row sm:items-center sm:justify-between ${className || ''}`}>
    <div className="flex min-w-0 items-center gap-3">
      {Icon && (
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary/10">
          <Icon className="h-5 w-5 text-primary" />
        </div>
      )}
      <div className="min-w-0">
        <h1 className="page-title">{title}</h1>
        {description && (
          <p className="mt-1 max-w-3xl text-sm leading-5 text-muted-foreground">{description}</p>
        )}
      </div>
    </div>
    {actions && (
      <div className="flex shrink-0 flex-wrap gap-2 sm:justify-end">
        {actions}
      </div>
    )}
  </header>
);

export default PageHeader;
