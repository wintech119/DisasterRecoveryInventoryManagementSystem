class OfflineStorage {
  constructor() {
    this.dbName = 'DRIMS_Offline';
    this.dbVersion = 1;
    this.db = null;
  }

  async init() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(this.dbName, this.dbVersion);

      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        this.db = request.result;
        resolve(this.db);
      };

      request.onupgradeneeded = (event) => {
        const db = event.target.result;

        if (!db.objectStoreNames.contains('pending_operations')) {
          const operationsStore = db.createObjectStore('pending_operations', { 
            keyPath: 'local_id', 
            autoIncrement: true 
          });
          operationsStore.createIndex('type', 'type', { unique: false });
          operationsStore.createIndex('created_at', 'created_at', { unique: false });
          operationsStore.createIndex('hub_id', 'hub_id', { unique: false });
        }

        if (!db.objectStoreNames.contains('cached_inventory')) {
          const inventoryStore = db.createObjectStore('cached_inventory', { 
            keyPath: 'hub_id' 
          });
          inventoryStore.createIndex('last_synced', 'last_synced', { unique: false });
        }

        if (!db.objectStoreNames.contains('cached_needs_lists')) {
          const needsListsStore = db.createObjectStore('cached_needs_lists', { 
            keyPath: 'list_id' 
          });
          needsListsStore.createIndex('hub_id', 'hub_id', { unique: false });
          needsListsStore.createIndex('last_synced', 'last_synced', { unique: false });
        }

        if (!db.objectStoreNames.contains('offline_session')) {
          db.createObjectStore('offline_session', { keyPath: 'key' });
        }

        if (!db.objectStoreNames.contains('sync_failures')) {
          const failuresStore = db.createObjectStore('sync_failures', { 
            keyPath: 'failure_id', 
            autoIncrement: true 
          });
          failuresStore.createIndex('created_at', 'created_at', { unique: false });
        }
      };
    });
  }

  async addPendingOperation(operation) {
    const transaction = this.db.transaction(['pending_operations'], 'readwrite');
    const store = transaction.objectStore('pending_operations');
    
    const operationData = {
      ...operation,
      created_at: new Date().toISOString(),
      client_id: this.generateClientId()
    };
    
    return new Promise((resolve, reject) => {
      const request = store.add(operationData);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async getPendingOperations() {
    const transaction = this.db.transaction(['pending_operations'], 'readonly');
    const store = transaction.objectStore('pending_operations');
    
    return new Promise((resolve, reject) => {
      const request = store.getAll();
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async removePendingOperation(localId) {
    const transaction = this.db.transaction(['pending_operations'], 'readwrite');
    const store = transaction.objectStore('pending_operations');
    
    return new Promise((resolve, reject) => {
      const request = store.delete(localId);
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  }

  async cacheInventory(hubId, inventoryData) {
    const transaction = this.db.transaction(['cached_inventory'], 'readwrite');
    const store = transaction.objectStore('cached_inventory');
    
    const cacheData = {
      hub_id: hubId,
      data: inventoryData,
      last_synced: new Date().toISOString()
    };
    
    return new Promise((resolve, reject) => {
      const request = store.put(cacheData);
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  }

  async getCachedInventory(hubId) {
    const transaction = this.db.transaction(['cached_inventory'], 'readonly');
    const store = transaction.objectStore('cached_inventory');
    
    return new Promise((resolve, reject) => {
      const request = store.get(hubId);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async storeSession(sessionData) {
    const transaction = this.db.transaction(['offline_session'], 'readwrite');
    const store = transaction.objectStore('offline_session');
    
    const data = {
      key: 'current_session',
      ...sessionData,
      stored_at: new Date().toISOString()
    };
    
    return new Promise((resolve, reject) => {
      const request = store.put(data);
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  }

  async getSession() {
    const transaction = this.db.transaction(['offline_session'], 'readonly');
    const store = transaction.objectStore('offline_session');
    
    return new Promise((resolve, reject) => {
      const request = store.get('current_session');
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async clearSession() {
    const transaction = this.db.transaction(['offline_session'], 'readwrite');
    const store = transaction.objectStore('offline_session');
    
    return new Promise((resolve, reject) => {
      const request = store.delete('current_session');
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  }

  async addSyncFailure(operation, error) {
    const transaction = this.db.transaction(['sync_failures'], 'readwrite');
    const store = transaction.objectStore('sync_failures');
    
    const failureData = {
      operation,
      error: error.toString(),
      created_at: new Date().toISOString()
    };
    
    return new Promise((resolve, reject) => {
      const request = store.add(failureData);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async getSyncFailures() {
    const transaction = this.db.transaction(['sync_failures'], 'readonly');
    const store = transaction.objectStore('sync_failures');
    
    return new Promise((resolve, reject) => {
      const request = store.getAll();
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async clearSyncFailure(failureId) {
    const transaction = this.db.transaction(['sync_failures'], 'readwrite');
    const store = transaction.objectStore('sync_failures');
    
    return new Promise((resolve, reject) => {
      const request = store.delete(failureId);
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  }

  generateClientId() {
    return `client_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }
}

window.OfflineStorage = OfflineStorage;
