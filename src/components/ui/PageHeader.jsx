const PageHeader = ({ title, icon: Icon, actions }) => (
  <div className="flex items-center justify-between mb-6">
    <h1 className="text-2xl font-bold flex items-center gap-2">
      {Icon && <Icon className="h-6 w-6" />}
      {title}
    </h1>
    <div className="flex gap-2">
      {actions}
    </div>
  </div>
);

export default PageHeader;
