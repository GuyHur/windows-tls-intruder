const config = {};

config.debug = true;
// =========================================================================
//  common.js — shared helpers loaded before every library-specific script.
// =========================================================================

// -- Message types ----------------------------------------------------------
const MessageType = {
    SEND: 's',
    RECV: 'r',
    CLOSE: 'c',
};

// -- Metadata keys ----------------------------------------------------------
const MetadataType = {
    SOCKET: 's',
    PROTOCOL: 'p',
    CONNECTION_ID: 'ci',
    CONNECTION_SOURCE_IP: 'csi',
    CONNECTION_SOURCE_PORT: 'csp',
    CONNECTION_SOURCE_PATH: 'cspa',
    CONNECTION_DESTINATION_IP: 'cdi',
    CONNECTION_DESTINATION_PORT: 'cdp',
    CONNECTION_DESTINATION_PATH: 'cdpa',
    MODULE: 'm',
};

// -- Unique message ID generator --------------------------------------------
const generateMessageId = () => {
    const S4 = () => (((1 + Math.random()) * 0x10000) | 0).toString(16).substring(1);
    return (S4() + S4() + '-' + S4() + '-' + S4() + '-' + S4() + '-' + S4() + S4() + S4());
};

// -- Synchronous intercept --------------------------------------------------
//  Sends the buffer to the host, then blocks until the host posts a response
//  back with the same message id.  Returns the response object whose `.data`
//  is a JS array of byte values.
const intercept = (type, message, buffer) => {
    message.id = message.id ? message.id : generateMessageId();
    message.type = type;

    send(message, buffer);

    let responseHolder = null;
    recv(message.id, response => {
        responseHolder = response;
    }).wait();

    return responseHolder;
};

const interceptSend = (message, buffer) => intercept(MessageType.SEND, message, buffer);
const interceptRecv = (message, buffer) => intercept(MessageType.RECV, message, buffer);

const process = (type, message) => {
    message.id = message.id ? message.id : generateMessageId();
    message.type = type;
    send(message);
};

const processClose = (message) => process(MessageType.CLOSE, message);

// -- Logging ----------------------------------------------------------------
const log = (level, ...message) => {
    console.log(new Date().toISOString(), '[' + level + '] (agent)', ...message);
};
const logInfo = (...message) => log('INFO', ...message);
const logWarning = (...message) => log('WARN', ...message);
const logError = (...message) => log('ERROR', ...message);
const logDebug = (...message) => config.debug ? log('DEBUG', ...message) : null;

// -- Module / library lookup ------------------------------------------------
const MODULES = Process.enumerateModules().reduce((map, mod) => {
    map[mod.name.toLowerCase()] = mod;
    return map;
}, {});

const attachToFunctionInLibraries = (libs, func, handlerCreator) => {
    libs.map(lib => lib.toLowerCase())
        .filter(lib => {
            if (lib in MODULES) {
                return true;
            }
            logInfo('Function', func, 'not found, since library', lib, 'is missing');
            return false;
        })
        .map(lib => ({
            name: lib,
            export: MODULES[lib].findExportByName(func)
        }))
        .filter(lib => {
            if (lib.export) {
                return true;
            }
            logInfo('Function', func, 'not found in library', lib.name);
            return false;
        })
        .forEach(lib => {
            Interceptor.attach(lib.export, handlerCreator(lib.name));
            logInfo('Hooked function', func, 'in library', lib.name);
        });
};

const attachToFunctionInLibrariesMatching = (libsNamesMatcher, func, handlerCreator) => {
    const matchingLibraries = Object.keys(MODULES)
            .filter(mod => libsNamesMatcher.some(libNameMatcher => mod.match(libNameMatcher)));

    if (matchingLibraries.length === 0) {
        logInfo('No matching libraries found for regexes', libsNamesMatcher);
    }

    matchingLibraries.map(lib => ({
            name: lib,
            export: MODULES[lib].findExportByName(func)
        }))
        .filter(lib => {
            if (lib.export) {
                return true;
            }
            logInfo('Function', func, 'not found in library', lib.name);
            return false;
        })
        .forEach(lib => {
            Interceptor.attach(lib.export, handlerCreator(lib.name));
            logInfo('Hooked function', func, 'in library', lib.name);
        });
};

// -- Buffer helpers ---------------------------------------------------------

const responseDataToBuffer = (responseData) => {
    return new Uint8Array(responseData).buffer;
};

/**
 * Safely write response.data into an existing buffer (clamped to bufferSize).
 * Returns the number of bytes written.
 */
const safeWriteToBuffer = (bufferPointer, bufferSize, responseData, silent) => {
    let sizedData;
    if (responseData.length > bufferSize) {
        sizedData = responseData.slice(0, bufferSize);
        if (silent !== true) {
            logInfo('Data overflows recv buffer, slicing from', responseData.length, 'to', bufferSize, 'bytes');
        }
    } else {
        sizedData = responseData;
    }

    const buffer = responseDataToBuffer(sizedData);
    bufferPointer.writeByteArray(buffer);

    return buffer.byteLength;
};

/**
 * Allocate a new buffer in process memory and copy response.data into it.
 * Store the return value in `this` to prevent GC between onEnter and onLeave.
 */
const createBufferInMemory = (responseData) => {
    const newBuffer = responseDataToBuffer(responseData);
    const buffer = Memory.alloc(newBuffer.byteLength);
    buffer.writeByteArray(newBuffer);
    return buffer;
};

// -- Socket metadata helpers ------------------------------------------------

const getMetadataFromSocket = (socket, moduleName) => {
    const metadata = {
        [MetadataType.SOCKET]: socket,
        [MetadataType.CONNECTION_ID]: moduleName + '-' + socket,
        [MetadataType.MODULE]: moduleName,
    };

    if (socket == null) {
        return metadata;
    }

    const protocol = Socket.type(socket);
    if (protocol == null) {
        return metadata;
    }

    metadata[MetadataType.PROTOCOL] = protocol;

    const localAddress = Socket.localAddress(socket);
    if (localAddress != null) {
        if (localAddress.hasOwnProperty('ip')) {
            metadata[MetadataType.CONNECTION_SOURCE_IP] = localAddress.ip;
            metadata[MetadataType.CONNECTION_SOURCE_PORT] = localAddress.port;
        } else if (localAddress.hasOwnProperty('path')) {
            metadata[MetadataType.CONNECTION_SOURCE_PATH] = localAddress.path;
        }
    }

    const peerAddress = Socket.peerAddress(socket);
    if (peerAddress != null) {
        if (peerAddress.hasOwnProperty('ip')) {
            metadata[MetadataType.CONNECTION_DESTINATION_IP] = peerAddress.ip;
            metadata[MetadataType.CONNECTION_DESTINATION_PORT] = peerAddress.port;
        } else if (peerAddress.hasOwnProperty('path')) {
            metadata[MetadataType.CONNECTION_DESTINATION_PATH] = peerAddress.path;
        }
    }

    return metadata;
};

const getMetadataFromCode = (code, moduleName) => {
    return {
        [MetadataType.CONNECTION_ID]: moduleName + '-' + code,
        [MetadataType.MODULE]: moduleName,
    };
};

// -- Info log ---------------------------------------------------------------
logInfo(`Process info: id=${Process.id} architecture=${Process.arch} platform=${Process.platform}`);


(function() {
    const module = {};module.type = 'openssl';module.config = {"libs": ["libssl", "openssl", "ssleay", "libeay", "libcrypto"], "SSL_write": true, "SSL_write_ex": true, "SSL_read": true, "SSL_read_ex": true, "SSL_shutdown": true};// =========================================================================
//  openssl.js — hooks for OpenSSL SSL_read / SSL_write (and _ex variants).
//  Library names are matched with regex so "libssl-3-x64.dll" etc. are
//  found automatically.
//  Ref: https://www.openssl.org/docs/man3.0/man3/SSL_read.html
// =========================================================================

const LIBS = module.config.libs || ["libssl", "openssl", "ssleay", "libeay", "libcrypto"];

// Cache SSL_get_fd native function per library for socket metadata lookup.
const getFdFunctions = new Map();

const getFd = (lib, ssl) => {
    if (getFdFunctions.has(lib)) {
        return getFdFunctions.get(lib)(ssl);
    }

    const SSL_get_fd_export = Module.findExportByName(lib, 'SSL_get_fd');
    if (SSL_get_fd_export) {
        const SSL_get_fd = new NativeFunction(SSL_get_fd_export, "int", ["pointer"]);
        getFdFunctions.set(lib, SSL_get_fd);
        return SSL_get_fd(ssl);
    }

    const noop = () => null;
    getFdFunctions.set(lib, noop);
    return noop(ssl);
};

const getMetadata = (lib, ssl) => {
    const socket = getFd(lib, ssl);
    return getMetadataFromSocket(socket, 'openssl');
};

/*
int SSL_write(SSL *ssl, const void *buf, int num);
*/
if (module.config.SSL_write) {
    attachToFunctionInLibrariesMatching(LIBS, 'SSL_write', (lib) => ({
        onEnter: function (args) {
            const ssl = args[0];
            const bufferPointer = args[1];
            this.originalDataSize = args[2].toInt32();
            const buffer = bufferPointer.readByteArray(this.originalDataSize);

            const response = interceptSend(getMetadata(lib, ssl), buffer);

            this.buffer = createBufferInMemory(response.data);

            args[1] = this.buffer;
            args[2] = new NativePointer(response.data.length);
        },
        onLeave: function (retval) {
            retval.replace(this.originalDataSize);
        }
    }));
}

/*
int SSL_write_ex(SSL *s, const void *buf, size_t num, size_t *written);
*/
if (module.config.SSL_write_ex) {
    attachToFunctionInLibrariesMatching(LIBS, 'SSL_write_ex', (lib) => ({
        onEnter: function (args) {
            const ssl = args[0];
            const bufferPointer = args[1];
            this.originalDataSize = args[2].toInt32();
            this.writtenPointer = args[3];
            const buffer = bufferPointer.readByteArray(this.originalDataSize);

            const response = interceptSend(getMetadata(lib, ssl), buffer);

            this.buffer = createBufferInMemory(response.data);

            args[1] = this.buffer;
            args[2] = new NativePointer(response.data.length);
        },
        onLeave: function (retval) {
            this.writtenPointer.writeInt(this.originalDataSize);
        }
    }));
}

/*
int SSL_read(SSL *ssl, void *buf, int num);
*/
if (module.config.SSL_read) {
    attachToFunctionInLibrariesMatching(LIBS, 'SSL_read', (lib) => ({
        onEnter: function (args) {
            this.ssl = args[0];
            this.bufferPointer = args[1];
            this.bufferSize = args[2].toInt32();
        },
        onLeave: function (retval) {
            const receivedDataSize = retval.toInt32();
            if (receivedDataSize <= 0) {
                return;
            }
            const receivedData = this.bufferPointer.readByteArray(receivedDataSize);

            const response = interceptRecv(getMetadata(lib, this.ssl), receivedData);

            const byteLength = safeWriteToBuffer(this.bufferPointer, this.bufferSize, response.data);

            retval.replace(byteLength);
        }
    }));
}

/*
int SSL_read_ex(SSL *ssl, void *buf, size_t num, size_t *readbytes);
*/
if (module.config.SSL_read_ex) {
    attachToFunctionInLibrariesMatching(LIBS, 'SSL_read_ex', (lib) => ({
        onEnter: function (args) {
            this.ssl = args[0];
            this.bufferPointer = args[1];
            this.bufferSize = args[2].toInt32();
            this.readPointer = args[3];
        },
        onLeave: function (retval) {
            const resultCode = retval.toInt32();
            if (resultCode !== 1) {
                return;
            }
            const receivedData = this.bufferPointer.readByteArray(this.readPointer.readInt());

            const response = interceptRecv(getMetadata(lib, this.ssl), receivedData);

            const byteLength = safeWriteToBuffer(this.bufferPointer, this.bufferSize, response.data);

            this.readPointer.writeInt(byteLength);
        }
    }));
}

/*
int SSL_shutdown(SSL *ssl);
*/
if (module.config.SSL_shutdown) {
    attachToFunctionInLibrariesMatching(LIBS, 'SSL_shutdown', (lib) => ({
        onEnter: function (args) {
            const ssl = args[0];
            processClose(getMetadata(lib, ssl));
        },
        onLeave: function (retval) {
        }
    }));
}

}());
    

(function() {
    const module = {};module.type = 'schannel';module.config = {"libs": ["Secur32.dll"], "EncryptMessage": true, "DecryptMessage": true};// =========================================================================
//  schannel.js — hooks for Windows Schannel (SSPI) TLS functions.
//  EncryptMessage / DecryptMessage operate on SecBufferDesc structures.
//  Ref: https://learn.microsoft.com/en-us/windows/win32/secauthn/schannel
// =========================================================================

const LIBS = module.config.libs || ["Secur32.dll"];

const BufferType = {
    DATA: 1,
};

/*
SecBufferDesc: { ULONG ulVersion; ULONG cBuffers; PSecBuffer pBuffers; }
SecBuffer:     { ULONG cbBuffer; ULONG BufferType; PVOID pvBuffer; }
*/
const interceptDataBuffer = (context, secBufferDescPointer, interceptFn) => {
    const buffersCount = secBufferDescPointer.add(4).readULong();
    const buffers = secBufferDescPointer.add(8).readPointer();

    let buffer = buffers;
    for (let i = 0; i < buffersCount; ++i) {
        const bufferType = buffer.add(4).readULong();

        if (bufferType === BufferType.DATA) {
            const bufferSize = buffer.readULong();
            const bufferPointer = buffer.add(8).readPointer();
            const data = bufferPointer.readByteArray(bufferSize);

            const response = interceptFn(getMetadataFromCode(context, 'schannel'), data);

            const newLength = safeWriteToBuffer(bufferPointer, bufferSize, response.data);

            buffer.writeULong(newLength);
        }

        buffer = buffer.add(8 + Process.pointerSize);
    }
};

/*
SECURITY_STATUS SEC_ENTRY EncryptMessage(
  [in]      PCtxtHandle    phContext,
  [in]      unsigned long  fQOP,
  [in, out] PSecBufferDesc pMessage,
  [in]      unsigned long  MessageSeqNo
);
*/
if (module.config.EncryptMessage) {
    attachToFunctionInLibraries(LIBS, 'EncryptMessage', (lib) => ({
        onEnter: function (args) {
            interceptDataBuffer(args[0], args[2], interceptSend);
        },
        onLeave: function (retval) {
        }
    }));
}

/*
SECURITY_STATUS SEC_ENTRY DecryptMessage(
  [in]      PCtxtHandle    phContext,
  [in, out] PSecBufferDesc pMessage,
  [in]      unsigned long  MessageSeqNo,
  [out]     unsigned long  *pfQOP
);
*/
if (module.config.DecryptMessage) {
    attachToFunctionInLibraries(LIBS, 'DecryptMessage', (lib) => ({
        onEnter: function (args) {
            this.phContext = args[0];
            this.pMessage = args[1];
        },
        onLeave: function (retval) {
            interceptDataBuffer(this.phContext, this.pMessage, interceptRecv);
        }
    }));
}

}());
    

(function() {
    const module = {};module.type = 'winsock';module.config = {"libs": ["ws2_32.dll", "wsock32.dll"], "send": true, "sendto": true, "recv": true, "recvfrom": true, "WSASend": true, "WSASendTo": true, "WSARecv": true, "WSARecvFrom": true, "closesocket": true, "shutdown": true};// =========================================================================
//  winsock.js — hooks for ws2_32 / wsock32 socket functions on Windows.
// =========================================================================

const LIBS = module.config.libs || ["ws2_32.dll", "wsock32.dll"];

// ── Basic Winsock: send / sendto ──────────────────────────────────────

const createSendHandler = (func) => ({
    onEnter: function (args) {
        const socket = args[0].toInt32();
        const bufferPointer = args[1];
        this.originalDataSize = args[2].toInt32();
        const buffer = bufferPointer.readByteArray(this.originalDataSize);

        const response = interceptSend(getMetadataFromSocket(socket, 'wsock'), buffer);

        this.buffer = createBufferInMemory(response.data);

        args[1] = this.buffer;
        args[2] = new NativePointer(response.data.length);
    },
    onLeave: function (retval) {
        retval.replace(this.originalDataSize);
    }
});

if (module.config.send) {
    attachToFunctionInLibraries(LIBS, 'send', () => createSendHandler('send'));
}

if (module.config.sendto) {
    attachToFunctionInLibraries(LIBS, 'sendto', () => createSendHandler('sendto'));
}

// ── Basic Winsock: recv / recvfrom ────────────────────────────────────

const createRecvHandler = (func) => ({
    onEnter: function (args) {
        this.socket = args[0].toInt32();
        this.bufferPointer = args[1];
        this.bufferSize = args[2].toInt32();
    },
    onLeave: function (retval) {
        const receivedDataSize = retval.toInt32();
        if (receivedDataSize <= 0) {
            return;
        }

        const receivedData = this.bufferPointer.readByteArray(receivedDataSize);

        const response = interceptRecv(getMetadataFromSocket(this.socket, 'wsock'), receivedData);

        const byteLength = safeWriteToBuffer(this.bufferPointer, this.bufferSize, response.data);

        retval.replace(byteLength);
    }
});

if (module.config.recv) {
    attachToFunctionInLibraries(LIBS, 'recv', () => createRecvHandler('recv'));
}

if (module.config.recvfrom) {
    attachToFunctionInLibraries(LIBS, 'recvfrom', () => createRecvHandler('recvfrom'));
}

// ── WSA buffer iteration ──────────────────────────────────────────────
// WSABUF layout: { ULONG len; CHAR *buf; }
// Stride is Process.pointerSize * 2 (4+4=8 on x86, 4+4pad+8=16 on x64)
// Pointer offset is Process.pointerSize (4 on x86, 8 on x64 due to padding)

const forEachWsaBuf = (buffersPointer, buffersCount, handler) => {
    let buffer = buffersPointer;
    for (let i = 0; i < buffersCount; ++i) {
        handler(buffer);
        buffer = buffer.add(Process.pointerSize * 2);
    }
};

// ── WSASend / WSASendTo ───────────────────────────────────────────────

const createWSASendHandler = (func) => ({
    onEnter: function (args) {
        const socket = args[0].toInt32();
        const buffers = args[1];
        const buffersCount = args[2].toInt32();
        this.sentBytesPointer = args[3];

        if (buffersCount <= 0) {
            return;
        }

        this.buffersInMemory = [];
        this.previousLength = 0;
        forEachWsaBuf(buffers, buffersCount, (buffer) => {
            const bufferSize = buffer.readULong();
            const bufferPointer = buffer.add(Process.pointerSize).readPointer();
            const data = bufferPointer.readByteArray(bufferSize);
            this.previousLength += bufferSize;

            const response = interceptSend(getMetadataFromSocket(socket, 'wsock'), data);

            const newBuffer = createBufferInMemory(response.data);
            this.buffersInMemory.push(newBuffer);

            buffer.writeULong(response.data.length);
            buffer.add(Process.pointerSize).writePointer(newBuffer);
        });
    },
    onLeave: function (retval) {
        if (retval.toInt32() !== 0) {
            return;
        }

        if (!this.sentBytesPointer.isNull()) {
            this.sentBytesPointer.writeInt(this.previousLength);
        }
    }
});

if (module.config.WSASend) {
    attachToFunctionInLibraries(LIBS, 'WSASend', () => createWSASendHandler('WSASend'));
}

if (module.config.WSASendTo) {
    attachToFunctionInLibraries(LIBS, 'WSASendTo', () => createWSASendHandler('WSASendTo'));
}

// ── WSARecv / WSARecvFrom ─────────────────────────────────────────────

const createWSARecvHandler = (func) => ({
    onEnter: function (args) {
        this.socket = args[0].toInt32();
        this.buffers = args[1];
        this.buffersCount = args[2].toInt32();
        this.receivedBytesPointer = args[3];
        this.flags = args[4];
        if (func === 'WSARecv') {
            this.overlapped = args[5];
            this.completionRoutine = args[6];
        } else if (func === 'WSARecvFrom') {
            this.overlapped = args[7];
            this.completionRoutine = args[8];
        }
    },
    onLeave: function (retval) {
        if (retval.toInt32() !== 0 || this.receivedBytesPointer.isNull()) {
            if (!this.overlapped.isNull()) {
                logWarning('Overlapped sockets are not supported!');
            }
            if (!this.completionRoutine.isNull()) {
                logWarning('Overlapped sockets are not supported!');
            }
            return;
        }

        const receivedSize = this.receivedBytesPointer.readULong();
        if (receivedSize <= 0) {
            return;
        }
        if (this.buffersCount <= 0) {
            return;
        }

        let dataToRead = receivedSize;
        let totalCapacity = 0;
        let totalBuffer = new Uint8Array(receivedSize);
        let offset = 0;
        forEachWsaBuf(this.buffers, this.buffersCount, (buffer) => {
            const bufferSize = buffer.readULong();
            const bufferPointer = buffer.add(Process.pointerSize).readPointer();
            totalCapacity += bufferSize;

            if (dataToRead <= 0) {
                return;
            }

            const dataToReadFromBuffer = (dataToRead >= bufferSize) ? bufferSize : dataToRead;

            const data = bufferPointer.readByteArray(dataToReadFromBuffer);
            totalBuffer.set(new Uint8Array(data), offset);

            dataToRead -= dataToReadFromBuffer;
            offset += dataToReadFromBuffer;
        });

        const response = interceptRecv(getMetadataFromSocket(this.socket, 'wsock'), totalBuffer.buffer);

        if (response.data.length > totalCapacity) {
            logInfo('Data will be trimmed from', response.data.length, 'to', totalCapacity, 'in order to fit into app buffers!');
        }

        let newLength = 0;
        let dataToWrite = response.data;
        forEachWsaBuf(this.buffers, this.buffersCount, (buffer) => {
            if (dataToWrite.length === 0) {
                return;
            }

            const bufferSize = buffer.readULong();
            const bufferPointer = buffer.add(Process.pointerSize).readPointer();

            const written = safeWriteToBuffer(bufferPointer, bufferSize, dataToWrite, true);

            dataToWrite = dataToWrite.slice(written);

            newLength += written;
        });

        if (!this.receivedBytesPointer.isNull()) {
            this.receivedBytesPointer.writeULong(newLength);
        }
    }
});

if (module.config.WSARecv) {
    attachToFunctionInLibraries(LIBS, 'WSARecv', () => createWSARecvHandler('WSARecv'));
}

if (module.config.WSARecvFrom) {
    attachToFunctionInLibraries(LIBS, 'WSARecvFrom', () => createWSARecvHandler('WSARecvFrom'));
}

// ── closesocket / shutdown ────────────────────────────────────────────

const createCloseHandler = (func) => ({
    onEnter: function (args) {
        const socket = args[0].toInt32();
        processClose(getMetadataFromSocket(socket, 'wsock'));
    },
    onLeave: function (retval) {
    }
});

if (module.config.closesocket) {
    attachToFunctionInLibraries(LIBS, 'closesocket', () => createCloseHandler('closesocket'));
}

if (module.config.shutdown) {
    attachToFunctionInLibraries(LIBS, 'shutdown', () => createCloseHandler('shutdown'));
}

}());
    