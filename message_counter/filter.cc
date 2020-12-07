#include <set>
#include <string>
#include <unordered_map>

#include "filter.pb.h"
#include "google/protobuf/util/json_util.h"
#include "proxy_wasm_intrinsics.h"

#define REQUEST_THRESHOLD 10
#define STORAGE_NAME "storage-upstream"
// toggle to enable counter over queue tracking
// #DEFINE COUNTER


enum class TrafficDirection : int64_t {
    Unspecified = 0,
    Inbound = 1,
    Outbound = 2,
};


// Retrieves the traffic direction from the configuration context.
TrafficDirection getTrafficDirection() {
    int64_t direction;
    if (getValue({"listener_direction"}, &direction)) {
        return static_cast<TrafficDirection>(direction);
    }
    return TrafficDirection::Unspecified;
}

std::string trafficDirectionToString(TrafficDirection dir) {
    if (dir == TrafficDirection::Unspecified) {
        return "unspecified";
    } else if (dir == TrafficDirection::Inbound) {
        return "inbound";
    } else {
        return "outbound";
    }
}

class BidiRootContext : public RootContext {
 public:
    explicit BidiRootContext(uint32_t id, std::string_view root_id)
        : RootContext(id, root_id) {
        std::string workload_name;
        if (getValue({"node", "metadata", "WORKLOAD_NAME"}, &workload_name)) {
            workload_name_ = workload_name;
            std::string warning = "initialized workload_name: ";
            warning = warning.append(workload_name_);
            LOG_WARN(warning);
        } else {
            LOG_WARN("Failed to set workload name");
        }
        int tmp_count = 0;
        std::string count_key = "count";
        proxy_set_shared_data(count_key.c_str(), count_key.size(),
                              (const char *)&tmp_count, sizeof(tmp_count), 0);
    }
    bool onConfigure(size_t /* configuration_size */) override;

    bool onStart(size_t) override;
    std::string getWorkloadName() { return workload_name_; }
    void incrementCount() {
        int *tmp_count;
        size_t *size;
        WasmResult result;

        std::string count_key = "count";
        result = proxy_get_shared_data(count_key.c_str(), count_key.size(),
                                       (const char **)&tmp_count, size, 0);
        if (result != WasmResult::Ok) {
            LOG_ERROR("Failed to get shared data " + count_key + ".");
            return;
        }
        (*tmp_count)++;
        result = proxy_set_shared_data(count_key.c_str(), count_key.size(),
                                       (const char *)tmp_count,
                                       sizeof(*tmp_count), 0);
        if (result != WasmResult::Ok) {
            LOG_ERROR("Failed to set shared data " + count_key + ".");
        }
    }
    void decrementCount() {
        WasmResult result;
        int *tmp_count;
        size_t *size;
        std::string count_key = "count";
        result = proxy_get_shared_data(count_key.c_str(), count_key.size(),
                                       (const char **)&tmp_count, size, 0);
        if (result != WasmResult::Ok) {
            LOG_ERROR("Failed to get shared data " + count_key + ".");
            return;
        }
        (*tmp_count)--;
        result = proxy_set_shared_data(count_key.c_str(), count_key.size(),
                                       (const char *)tmp_count,
                                       sizeof(*tmp_count), 0);
        if (result != WasmResult::Ok) {
            LOG_ERROR("Failed to set shared data " + count_key + ".");
        }
    }
    int getCount() {
        WasmResult result;
        int *tmp_count;
        size_t *size;
        std::string count_key = "count";
        result = proxy_get_shared_data(count_key.c_str(), count_key.size(),
                                       (const char **)&tmp_count, size, 0);
        if (result != WasmResult::Ok) {
            LOG_ERROR("Failed to get shared data " + count_key + ".");
            return -1;
        }
        return *tmp_count;
    }
    std::string header_value_;
    std::set<std::string> pending_requests;

 private:
    std::string workload_name_;
};

class BidiContext : public Context {
 public:
    explicit BidiContext(uint32_t id, RootContext *root)
        : Context(id, root),
          root_(static_cast<BidiRootContext *>(static_cast<void *>(root))) {
        direction_ = getTrafficDirection();

        gauge_ = Gauge<int>::New("queue_gauge", "queue_size");
    }

    void onCreate() override;
    FilterHeadersStatus onRequestHeaders(uint32_t headers,
                                         bool end_of_stream) override;
    FilterHeadersStatus onRequestHeadersInbound();
    FilterHeadersStatus onRequestHeadersOutbound();
    FilterDataStatus onRequestBody(size_t body_buffer_length,
                                   bool end_of_stream) override;
    FilterDataStatus onResponseBody(size_t body_buffer_length,
                                    bool end_of_stream) override;
    FilterHeadersStatus onResponseHeaders(uint32_t headers,
                                          bool end_of_stream) override;
    FilterHeadersStatus onResponseHeadersInbound();
    FilterHeadersStatus onResponseHeadersOutbound();

    void onDone() override;
    void onLog() override;
    void onDelete() override;

 private:
    BidiRootContext *root_;
    TrafficDirection direction_;
    Gauge<int> *gauge_;
    WasmResult store_warning();
    void print_headers(WasmHeaderMapType type);
};

static RegisterContextFactory
    register_BidiContext(CONTEXT_FACTORY(BidiContext),
                         ROOT_FACTORY(BidiRootContext), "bidi_root_id");

WasmResult BidiContext::store_warning() {
    std::string key = toString(getCurrentTimeNanoseconds());
    std::string value = root_->getWorkloadName();
    LOG_WARN("Storing timestamp " + key + " as node " + value + ".");
    auto context_id = id();
    auto callback = [context_id](uint32_t, size_t body_size, uint32_t) {
        getContext(context_id)->setEffectiveContext();
        auto body =
            getBufferBytes(WasmBufferType::HttpCallResponseBody, 0, body_size);
        LOG_WARN(std::string(body->view()));
    };
    auto result = root()->httpCall(STORAGE_NAME,
                                   {{":method", "GET"},
                                    {":path", "/store"},
                                    {":authority", STORAGE_NAME},
                                    {"key", key},
                                    {"value", value}},
                                   "", {}, 1000, callback);
    if (result != WasmResult::Ok) {
        LOG_ERROR("Failed to make a call to " + STORAGE_NAME + ": " +
                  toString(result));
    }
    return result;
}

void BidiContext::print_headers(WasmHeaderMapType type) {
    if (type == WasmHeaderMapType::RequestHeaders) {
        auto result = getRequestHeaderPairs();
        auto pairs = result->pairs();
        LOG_WARN("Request headers: " + toString(pairs.size()));
        for (auto &p : pairs) {
            LOG_WARN(std::string(p.first) + " -> " + std::string(p.second));
        }
    } else if (type == WasmHeaderMapType::ResponseHeaders) {
        auto result = getResponseHeaderPairs();
        auto pairs = result->pairs();
        LOG_WARN("Response headers: " + toString(pairs.size()));
        for (auto &p : pairs) {
            LOG_WARN(std::string(p.first) + " -> " + std::string(p.second));
        }
    }
}

////////////////// REQUEST HEADERS //////////////////

FilterHeadersStatus BidiContext::onRequestHeaders(uint32_t, bool) {
    FilterHeadersStatus status;

    LOG_WARN("REQUEST BEGIN ############################################");
    // Print all request headers
    print_headers(WasmHeaderMapType::RequestHeaders);

    replaceRequestHeader("x-envoy-force-trace", "true");
    if (direction_ == TrafficDirection::Inbound) {
        status = onRequestHeadersInbound();
    } else if (direction_ == TrafficDirection::Outbound) {
        status = onRequestHeadersOutbound();
    } else {
        LOG_ERROR("Missing request header direction.");
        status = FilterHeadersStatus::Continue;
    }
    LOG_WARN("REQUEST END ############################################");
    return status;
}

FilterHeadersStatus BidiContext::onRequestHeadersInbound() {
    LOG_WARN("Inbound request.");
    int curr_queue_size;
#ifdef COUNTER
    root_->incrementCount();
    curr_queue_size = root_->getCount();
#else
    auto request_id = getRequestHeader("x-request-id");
    if (request_id->data() == nullptr) {
        LOG_WARN(trafficDirectionToString(direction_) + " " +
                 "x-request-id not found!");
        return FilterHeadersStatus::Continue;
    }
    std::string x_request_id_ = request_id->toString();
    LOG_WARN("Inserting pending request " + x_request_id_ + ".");
    root_->pending_requests.insert(x_request_id_);
    curr_queue_size = root_->pending_requests.size();
#endif
    // gauge_->record(curr_queue_size, 0);
    LOG_WARN("Current size of request queue: " + toString(curr_queue_size));
    if (curr_queue_size > REQUEST_THRESHOLD) {
        LOG_ERROR("Request queue " + toString(curr_queue_size) +
                  " is above threshold " + toString(REQUEST_THRESHOLD) + ".");
        store_warning();
    }
    return FilterHeadersStatus::Continue;
}

FilterHeadersStatus BidiContext::onRequestHeadersOutbound() {
    LOG_WARN("Outbound request.");
    return FilterHeadersStatus::Continue;
}

////////////////// RESPONSE HEADERS //////////////////

FilterHeadersStatus BidiContext::onResponseHeaders(uint32_t, bool) {
    FilterHeadersStatus status;

    LOG_WARN("RESPONSE BEGIN ############################################");
    print_headers(WasmHeaderMapType::ResponseHeaders);
    replaceResponseHeader("location", "envoy-wasm");
    replaceResponseHeader("x-envoy-force-trace", "true");
    if (direction_ == TrafficDirection::Inbound) {
        status = onResponseHeadersInbound();
    } else if (direction_ == TrafficDirection::Outbound) {
        status = onResponseHeadersOutbound();
    } else {
        LOG_ERROR("Missing response header direction.");
        status = FilterHeadersStatus::Continue;
    }
    LOG_WARN("RESPONSE END ############################################");
    return status;
}

FilterHeadersStatus BidiContext::onResponseHeadersInbound() {
    LOG_WARN("Inbound response.");
    int curr_queue_size;
#ifdef COUNTER
    root_->decrementCount();
    curr_queue_size = root_->getCount();
#else
    auto request_id = getResponseHeader("x-request-id");
    if (request_id->data() == nullptr) {
        LOG_WARN(trafficDirectionToString(direction_) + " " +
                 "x-request-id not found!");
        return FilterHeadersStatus::Continue;
    }
    std::string x_request_id_ = request_id->toString();
    root_->pending_requests.erase(x_request_id_);
    curr_queue_size = root_->pending_requests.size();
    LOG_WARN("Removing pending request " + x_request_id_ + ".");
#endif
    gauge_->record(curr_queue_size, 0);
    LOG_WARN("Current size of request queue: " + toString(curr_queue_size));
    return FilterHeadersStatus::Continue;
}

FilterHeadersStatus BidiContext::onResponseHeadersOutbound() {
    LOG_WARN("Outbound response.");
    return FilterHeadersStatus::Continue;
}

////////////////// REQUEST BODY //////////////////

FilterDataStatus BidiContext::onRequestBody(size_t body_buffer_length,
                                            bool end_of_stream) {
    return FilterDataStatus::Continue;
}

////////////////// RESPONSE BODY //////////////////

FilterDataStatus BidiContext::onResponseBody(size_t body_buffer_length,
                                             bool end_of_stream) {
    return FilterDataStatus::Continue;
}

////////////////// CONFIGURE //////////////////

bool BidiRootContext::onConfigure(size_t config_buffer_length) {
    auto conf = getBufferBytes(WasmBufferType::PluginConfiguration, 0,
                               config_buffer_length);
    LOG_DEBUG("onConfigure " + conf->toString());
    header_value_ = conf->toString();
    return true;
}

////////////////// START //////////////////

bool BidiRootContext::onStart(size_t) {
    LOG_DEBUG("onStart");
    return true;
}

////////////////// CREATE //////////////////

void BidiContext::onCreate() {
    LOG_DEBUG(std::string("onCreate " + toString(id())));
}

////////////////// DONE //////////////////

void BidiContext::onDone() {
    LOG_DEBUG(std::string("onDone " + toString(id())));
}

////////////////// LOG //////////////////

void BidiContext::onLog() { LOG_DEBUG(std::string("onLog " + toString(id()))); }

////////////////// DELETE //////////////////

void BidiContext::onDelete() {
    LOG_DEBUG(std::string("onDelete " + toString(id())));
}
