#include "stdafx.h"

#include "external_port.h"

#include <iostream>

#include "asio.h"
#include "cfg.h"
#include "encryption.h"
#include "realtime.h"

using asio::ip::tcp;

// This namespace contains classes used for external communication, for example
// with Monitor
namespace cma::world {

// below is working example from asio
// verified and working, Example is Echo TCP
// try not damage it

// will not used normally by agent
void AsioSession::do_read() {
    auto self(shared_from_this());
    socket_.async_read_some(
        asio::buffer(data_, kMaxLength),  // data will be ignored
        [this, self](std::error_code ec, std::size_t length) {
            if (!ec) {
                char internal_data[124] = "Answer!\n";
                do_write(internal_data, strlen(internal_data) + 1, nullptr);
            }
        });
}

size_t AsioSession::allocCryptBuffer(
    const cma::encrypt::Commander *Crypt) noexcept {
    if (!Crypt) return 0;

    if (!Crypt->blockSize().has_value()) {
        XLOG::l("Impossible situation, crypt engine is absent");
        return 0;
    }

    if (!Crypt->blockSize().value()) {
        XLOG::l("Impossible situation, block is too short");
        return 0;
    }

    size_t crypt_segment_size = 0;
    try {
        // calculating length and allocating persistent memory
        auto block_size = Crypt->blockSize().value();
        crypt_segment_size = (segment_size_ / block_size + 1) * block_size;
        crypt_buf_.reset(new char[crypt_segment_size]);
        XLOG::d.i("Encrypted output block {} bytes, crypt buffer {} bytes...",
                  block_size, crypt_segment_size);

    } catch (const std::exception &e) {
        XLOG::l.crit(XLOG_FUNC + " unexpected, but exception '{}'", e.what());
        return 0;
    }
    return crypt_segment_size;
}

// returns 0 on failure
static size_t WriteDataToSocket(asio::ip::tcp::socket &sock, const char *data,
                                size_t sz) noexcept {
    using namespace asio;

    if (nullptr == data) {
        XLOG::l.bp(XLOG_FUNC + " nullptr in");
        return 0;
    }

    // asio execution
    std::error_code ec;
    auto written_bytes =
        write(sock, buffer(data, sz), transfer_exactly(sz), ec);

    // error processing
    if (ec.value() != 0) {
        XLOG::d(XLOG_FUNC + " write [{}] bytes to socket failed [{}] '{}'", sz,
                ec.value(), ec.message());
        return 0;
    }

    return written_bytes;
}

// returns 0 on failure
static size_t WriteStringToSocket(asio::ip::tcp::socket &sock,
                                  std::string_view str) noexcept {
    return WriteDataToSocket(sock, str.data(), str.size());
}

// To send data
void AsioSession::do_write(const void *Data, std::size_t Length,
                           cma::encrypt::Commander *Crypt) {
    auto self(shared_from_this());

    auto data = static_cast<const char *>(Data);
    auto crypt_buf_len = allocCryptBuffer(Crypt);

    while (Length) {
        // we will send data in relatively small chunks
        // asio is stupid enough and cannot send big data blocks
        auto to_send = std::min(Length, segment_size_);

        const bool async = false;
        if (async) {
            // code below is written in theory correct, but performance is
            // terrible and absolutely unpredictable
            asio::async_write(
                socket_, asio::buffer(data, to_send),
                [this, self, to_send, Length](std::error_code ec,
                                              std::size_t length) {
                    XLOG::t.i(
                        "Send [{}] from [{}] data with code [{}] left to send [{}]",
                        length, to_send, ec.value(), Length);
                });
        } else {
            // correct code is here
            size_t written_bytes = 0;
            if (Crypt) {
                if (!crypt_buf_len) {
                    XLOG::l("Encrypt is requested, but encryption is failed");
                    return;
                }

                // encryption
                auto buf = crypt_buf_.get();
                memcpy(buf, data, to_send);
                auto [success, len] = Crypt->encode(buf, to_send, crypt_buf_len,
                                                    Length == to_send);
                // checking
                if (!success) {
                    XLOG::l.crit(XLOG_FUNC + "CANNOT ENCRYPT {}.", len);
                    return;
                }

                // sending
                // suboptimal method, but one additional packet pro 1 minute
                // means for TCP nothing. Still candidate to optimize
                if (static_cast<const void *>(data) == Data)
                    WriteStringToSocket(socket_, cma::rt::kPlainHeader);

                written_bytes = WriteDataToSocket(socket_, buf, len);

            } else
                written_bytes = WriteDataToSocket(socket_, data, to_send);

            XLOG::t.i("Send [{}] from [{}] data to send [{}]", written_bytes,
                      to_send, Length);
        }

        // send;
        Length -= to_send;
        data += to_send;
    }
}

}  // namespace cma::world

namespace cma::world {

// wake thread too
void ExternalPort::putOnQueue(AsioSession::s_ptr asio_session) {
    // short block
    bool loaded = false;
    std::unique_lock lk(queue_lock_);
    auto size = session_queue_.size();
    if (size < kMaxSessionQueueLength) {
        session_queue_.push(asio_session);
        loaded = true;
        size = session_queue_.size();
    }
    lk.unlock();

    if (loaded) {
        wakeThread();
        XLOG::d.i("Put on queue, size is [{}]", size);
    } else {
        XLOG::d("queue is overflown");
    }
}

// thread safe
// may return empty shared ptr
AsioSession::s_ptr ExternalPort::getSession() {
    std::unique_lock lk(queue_lock_);

    if (session_queue_.empty()) return {};

    auto as = session_queue_.front();
    session_queue_.pop();
    auto sz = session_queue_.size();
    lk.unlock();

    XLOG::d.i("Found connection on queue, in queue left[{}]", sz);
    return as;
}

void ExternalPort::timedWaitForSession() {
    using namespace std::chrono;
    std::unique_lock lk(wake_lock_);
    wake_thread_.wait_until(lk, steady_clock::now() + wake_delay_,
                            [this]() { return !session_queue_.empty(); });
}

// singleton thread
void ExternalPort::processQueue(cma::world::ReplyFunc reply) noexcept {
    for (;;) {
        // we must to catch exception in every thread, even so simple one
        try {
            // processing block
            auto as = getSession();

            if (as) {
                const auto [ip, ipv6] = GetSocketInfo(as->currentSocket());
                XLOG::d.i("Connected from '{}' ipv6:{} <- queue", ip, ipv6);

                // only_from checking
                if (cma::cfg::groups::global.isIpAddressAllowed(ip)) {
                    as->start(reply);
                } else {
                    XLOG::d(
                        "Address '{}' is not allowed, this call should happen",
                        ip);
                }
            }

            // wake block
            timedWaitForSession();

            // stop block
            if (isShutdown()) break;
        } catch (const std::exception &e) {
            XLOG::l.bp(XLOG_FUNC + " Unexpected exception '{}'", e.what());
        }
    }

    XLOG::l.i("Exiting process queue");
}

void ExternalPort::wakeThread() {
    std::lock_guard l(wake_lock_);
    wake_thread_.notify_one();
}

bool sinkProc(cma::world::AsioSession::s_ptr asio_session,
              ExternalPort *ex_port) {
    ex_port->putOnQueue(asio_session);
    return true;
}

// Main IO thread
// MAY BE RESTARTED if we have new port/ipv6 mode in config
// OneShot - true, CMK way, connect, send data back, disconnect
//         - false, accept send data back, no disconnect
void ExternalPort::ioThreadProc(cma::world::ReplyFunc Reply) {
    using namespace cma::cfg;
    XLOG::t(XLOG_FUNC + " started");
    // all threads must control exceptions
    try {
        auto ipv6 = groups::global.ipv6();

        // important diagnostic
        {
            if (owner_) owner_->preContextCall();

            // asio magic here
            asio::io_context context;

            ipv6 = groups::global.ipv6();
            auto port =
                default_port_ == 0 ? groups::global.port() : default_port_;

            // server start
            ExternalPort::server sock(context, ipv6, port);
            XLOG::l.i("Starting IO ipv6:{}, used port:{}", ipv6, port);
            sock.run_accept(sinkProc, this);

            registerContext(&context);

            // server thread start
            auto processor_thread =
                std::thread(&ExternalPort::processQueue, this, Reply);

            // tcp body
            auto ret = context.run();  // run itself
            XLOG::t(XLOG_FUNC + " ended context with code[{}]", ret);

            if (processor_thread.joinable()) processor_thread.join();

            // no more reliable context here, delete it
            if (!registerContext(nullptr))  // no more stopping
            {
                XLOG::l.i(XLOG_FUNC + " terminated from outside");
            }
        }
        XLOG::l.i("IO ends...");

    } catch (std::exception &e) {
        registerContext(nullptr);  // cleanup
        std::cerr << "Exception: " << e.what() << "\n";
        XLOG::l(XLOG::kCritError)("IO broken with exception {}", e.what());
    }
}

// runs thread
// can fail when thread is already running
bool ExternalPort::startIo(ReplyFunc Reply) {
    std::lock_guard lk(io_thread_lock_);
    if (io_thread_.joinable()) return false;  // thread is in exec state

    shutdown_thread_ = false;  // reset potentially dropped flag

    io_thread_ = std::thread(&ExternalPort::ioThreadProc, this, Reply);
    io_started_ = true;
    return true;
}

// blocking call, signals thread and wait
void ExternalPort::shutdownIo() {
    // we just stopping, object is thread safe
    XLOG::l.i("Shutting down IO...");
    stopExecution();

    bool should_wait = false;
    {
        std::lock_guard lk(io_thread_lock_);
        should_wait = io_thread_.joinable();  // normal execution
        io_started_ = false;
    }

    if (should_wait) {
        io_thread_.join();
    }
}

}  // namespace cma::world
