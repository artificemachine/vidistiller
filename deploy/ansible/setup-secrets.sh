#!/usr/bin/env bash
# Generates vars/secrets.yml and .vault-pass for Ansible Vault.
# Existing .vault-pass is reused if present; otherwise prompts for a passphrase.
# Run: ./setup-secrets.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS="$SCRIPT_DIR/vars/secrets.yml"
VAULT_PASS="$SCRIPT_DIR/.vault-pass"

# --- Vault passphrase ---
if [[ -f "$VAULT_PASS" ]]; then
  echo "Reusing existing .vault-pass"
else
  read -rsp "Set vault passphrase: " VPASS; echo
  echo "$VPASS" > "$VAULT_PASS"
  chmod 600 "$VAULT_PASS"
  echo "Written: $VAULT_PASS"
fi

# --- Generate secrets ---
DB_PASSWORD=$(openssl rand -hex 32)
REDIS_PASSWORD=$(openssl rand -hex 32)
JWT_SECRET_KEY=$(openssl rand -hex 32)
FIELD_ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
PGADMIN_PASSWORD=$(openssl rand -hex 16)

cat > "$SECRETS" <<EOF
db_password: "$DB_PASSWORD"
redis_password: "$REDIS_PASSWORD"
jwt_secret_key: "$JWT_SECRET_KEY"
field_encryption_key: "$FIELD_ENCRYPTION_KEY"
pgadmin_email: "admin@vidistiller.local"
pgadmin_password: "$PGADMIN_PASSWORD"
timezone: "UTC"
EOF

chmod 600 "$SECRETS"
echo "Written: $SECRETS"

# --- Encrypt with vault ---
ansible-vault encrypt "$SECRETS" --vault-password-file "$VAULT_PASS"
echo "Encrypted: $SECRETS"
echo "Done — run: ansible-playbook site.yml"
