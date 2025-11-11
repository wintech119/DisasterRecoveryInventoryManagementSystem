/**
 * Offline Encryption Module
 * 
 * Provides Web Crypto API-based encryption for secure offline session storage.
 * Uses PBKDF2 for key derivation from user PIN and AES-GCM for encryption.
 */

class OfflineEncryption {
    constructor() {
        this.PBKDF2_ITERATIONS = 100000;
        this.SALT_LENGTH = 16;
        this.IV_LENGTH = 12;
        this.KEY_LENGTH = 256;
    }

    /**
     * Generate a random salt for PBKDF2
     */
    async generateSalt() {
        return crypto.getRandomValues(new Uint8Array(this.SALT_LENGTH));
    }

    /**
     * Generate a random IV for AES-GCM
     */
    async generateIV() {
        return crypto.getRandomValues(new Uint8Array(this.IV_LENGTH));
    }

    /**
     * Derive an encryption key from a user-provided PIN using PBKDF2
     */
    async deriveKey(pin, salt) {
        const encoder = new TextEncoder();
        const pinBuffer = encoder.encode(pin);
        
        // Import the PIN as a key
        const baseKey = await crypto.subtle.importKey(
            'raw',
            pinBuffer,
            'PBKDF2',
            false,
            ['deriveKey']
        );

        // Derive the actual encryption key
        return await crypto.subtle.deriveKey(
            {
                name: 'PBKDF2',
                salt: salt,
                iterations: this.PBKDF2_ITERATIONS,
                hash: 'SHA-256'
            },
            baseKey,
            { name: 'AES-GCM', length: this.KEY_LENGTH },
            false,
            ['encrypt', 'decrypt']
        );
    }

    /**
     * Encrypt data using AES-GCM
     * @param {string} data - Data to encrypt
     * @param {string} pin - User's offline PIN
     * @returns {Object} - {ciphertext, iv, salt} all as base64 strings
     */
    async encrypt(data, pin) {
        const encoder = new TextEncoder();
        const dataBuffer = encoder.encode(data);

        // Generate salt and IV
        const salt = await this.generateSalt();
        const iv = await this.generateIV();

        // Derive encryption key from PIN
        const key = await this.deriveKey(pin, salt);

        // Encrypt the data
        const ciphertext = await crypto.subtle.encrypt(
            {
                name: 'AES-GCM',
                iv: iv
            },
            key,
            dataBuffer
        );

        // Convert to base64 for storage
        return {
            ciphertext: this.arrayBufferToBase64(ciphertext),
            iv: this.arrayBufferToBase64(iv),
            salt: this.arrayBufferToBase64(salt),
            timestamp: Date.now()
        };
    }

    /**
     * Decrypt data using AES-GCM
     * @param {Object} encryptedData - {ciphertext, iv, salt} as base64 strings
     * @param {string} pin - User's offline PIN
     * @returns {string} - Decrypted data
     */
    async decrypt(encryptedData, pin) {
        // Convert from base64
        const ciphertext = this.base64ToArrayBuffer(encryptedData.ciphertext);
        const iv = this.base64ToArrayBuffer(encryptedData.iv);
        const salt = this.base64ToArrayBuffer(encryptedData.salt);

        // Derive encryption key from PIN
        const key = await this.deriveKey(pin, salt);

        // Decrypt the data
        try {
            const decryptedBuffer = await crypto.subtle.decrypt(
                {
                    name: 'AES-GCM',
                    iv: iv
                },
                key,
                ciphertext
            );

            const decoder = new TextDecoder();
            return decoder.decode(decryptedBuffer);
        } catch (e) {
            throw new Error('Decryption failed - incorrect PIN or corrupted data');
        }
    }

    /**
     * Create a PIN verification hash (stored alongside encrypted data)
     */
    async createPINVerifier(pin, salt) {
        const encoder = new TextEncoder();
        const pinBuffer = encoder.encode(pin);
        const combinedBuffer = new Uint8Array(pinBuffer.length + salt.length);
        combinedBuffer.set(pinBuffer);
        combinedBuffer.set(new Uint8Array(salt), pinBuffer.length);

        const hashBuffer = await crypto.subtle.digest('SHA-256', combinedBuffer);
        return this.arrayBufferToBase64(hashBuffer);
    }

    /**
     * Verify a PIN against stored hash
     */
    async verifyPIN(pin, salt, storedHash) {
        const computedHash = await this.createPINVerifier(pin, this.base64ToArrayBuffer(salt));
        return computedHash === storedHash;
    }

    /**
     * Convert ArrayBuffer to Base64 string
     */
    arrayBufferToBase64(buffer) {
        const bytes = new Uint8Array(buffer);
        let binary = '';
        for (let i = 0; i < bytes.byteLength; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        return btoa(binary);
    }

    /**
     * Convert Base64 string to ArrayBuffer
     */
    base64ToArrayBuffer(base64) {
        const binary = atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
        }
        return bytes.buffer;
    }
}

// Export for use in other modules
window.OfflineEncryption = OfflineEncryption;
