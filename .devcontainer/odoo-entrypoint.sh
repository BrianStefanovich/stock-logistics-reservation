#!/bin/sh
set -eu

config="${ODOO_CONFIG:-/workspace/odoo-develop-environment/config/odoo.conf}"

expand_init_glob() {
    case "$2" in
        *'*'*|*'?'*|*'['*) ;;
        *) printf '%s\n' "$2"; return 0 ;;
    esac

    modules=""
    for module_path in $2; do
        [ -f "$module_path/__manifest__.py" ] || continue
        module_name=$(basename "$module_path")
        modules="${modules:+$modules,}$module_name"
    done

    [ -n "$modules" ] || {
        echo "No Odoo modules found for init glob: $2" >&2
        exit 2
    }

    printf '%s\n' "$modules"
}

# Passing a command makes the container useful for one-off development tasks.
if [ "$#" -gt 0 ]; then
    case "$1" in
        -i|--init)
            init_option=$1
            init_modules=$(expand_init_glob "$@")
            shift 2
            set -- "$init_option" "$init_modules" "$@"
            ;;
    esac
    case "$1" in
        -*) set -- /usr/bin/odoo --config="$config" "$@" ;;
    esac
    exec "$@"
fi

if [ "${ODOO_AUTO_START:-true}" = "true" ]; then
    exec /usr/bin/odoo --config="$config"
fi

echo "Automatic Odoo startup is disabled. Run: odoo --config=$config"
exec sleep infinity
