"""Target-code templates for the fixed Rails project files.

Produces the project skeleton (Gemfile, config, controllers, spec helpers) around the
generated workflow. Only the process name and class names are substituted into the templates.
"""

from __future__ import annotations

from typing import Dict

from ...flowspec.ast.nodes import ProcessAST
from .naming import to_pascal_case
from .templates.rails_templates import (
    APPLICATION_CONTROLLER_TEMPLATE,
    APPLICATION_RB_TEMPLATE,
    AUTOLOAD_NAMESPACES_INITIALIZER_TEMPLATE,
    BIN_RAILS_TEMPLATE,
    BIN_RAKE_TEMPLATE,
    BOOT_RB_TEMPLATE,
    CONFIG_RU_TEMPLATE,
    ENV_DEVELOPMENT_TEMPLATE,
    ENV_EXAMPLE_TEMPLATE,
    ENV_PRODUCTION_TEMPLATE,
    ENV_TEST_TEMPLATE,
    ENVIRONMENT_RB_TEMPLATE,
    GEMFILE_TEMPLATE,
    PUMA_RB_TEMPLATE,
    RAILS_GITIGNORE_TEMPLATE,
    RAILS_HELPER_TEMPLATE,
    RAILS_README_TEMPLATE,
    RAKEFILE_TEMPLATE,
    ROUTES_RB_TEMPLATE,
    SIDEKIQ_INITIALIZER_TEMPLATE,
    SIDEKIQ_YML_TEMPLATE,
    SPEC_HELPER_TEMPLATE,
    WORKFLOWS_CONTROLLER_TEMPLATE,
)


def build_rails_scaffold(ast: ProcessAST, proc_snake: str, workflow_class_name: str) -> Dict[str, str]:
    app_module_name = to_pascal_case(ast.process_id)
    process_name = ast.name or ast.process_id
    return {
        "Gemfile": GEMFILE_TEMPLATE,
        "Rakefile": RAKEFILE_TEMPLATE,
        "config.ru": CONFIG_RU_TEMPLATE,
        ".env.example": ENV_EXAMPLE_TEMPLATE,
        ".gitignore": RAILS_GITIGNORE_TEMPLATE,
        "README.md": RAILS_README_TEMPLATE.format(
            app_module_name=app_module_name,
            process_id=ast.process_id,
            process_name=process_name,
            proc_snake=proc_snake,
        ),
        "bin/rails": BIN_RAILS_TEMPLATE,
        "bin/rake": BIN_RAKE_TEMPLATE,
        "config/boot.rb": BOOT_RB_TEMPLATE,
        "config/environment.rb": ENVIRONMENT_RB_TEMPLATE,
        "config/application.rb": APPLICATION_RB_TEMPLATE.format(app_module_name=app_module_name),
        "config/puma.rb": PUMA_RB_TEMPLATE,
        "config/routes.rb": ROUTES_RB_TEMPLATE.format(proc_snake=proc_snake),
        "config/sidekiq.yml": SIDEKIQ_YML_TEMPLATE,
        "config/initializers/autoload_namespaces.rb": AUTOLOAD_NAMESPACES_INITIALIZER_TEMPLATE,
        "config/initializers/sidekiq.rb": SIDEKIQ_INITIALIZER_TEMPLATE,
        "config/environments/development.rb": ENV_DEVELOPMENT_TEMPLATE,
        "config/environments/production.rb": ENV_PRODUCTION_TEMPLATE,
        "config/environments/test.rb": ENV_TEST_TEMPLATE,
        "app/controllers/application_controller.rb": APPLICATION_CONTROLLER_TEMPLATE,
        "app/controllers/workflows_controller.rb": WORKFLOWS_CONTROLLER_TEMPLATE.format(
            process_id=ast.process_id,
            workflow_class_name=workflow_class_name,
        ),
        "log/.keep": "",
        "tmp/.keep": "",
        "spec/spec_helper.rb": SPEC_HELPER_TEMPLATE,
        "spec/rails_helper.rb": RAILS_HELPER_TEMPLATE,
    }
