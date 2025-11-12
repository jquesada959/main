from cryptography.fernet import Fernet

# Generate a key and save it to a file
key = Fernet.generate_key()
with open('secret.admin.key', 'wb') as key_file:
    key_file.write(key)

# Read credentials.txt and encrypt its contents
with open('admin_creds.txt', 'rb') as f:
    data = f.read()

fernet = Fernet(key)
encrypted = fernet.encrypt(data)

with open('credentials.txt.admin.enc', 'wb') as f:
    f.write(encrypted)

print('Encryption complete. Encrypted file: credentials.txt.admin.enc')
print('Key saved to: secret.admin.key')
