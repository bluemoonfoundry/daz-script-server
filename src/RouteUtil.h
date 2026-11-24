#pragma once
// Small helpers shared by the route handler translation units.
#include "httplib.h"
#include "ErrorResponse.h"
#include <string>

// Write an ErrorResponse body with the code's HTTP status.
inline void respondError(httplib::Response& res, ErrorCode code, const std::string& detail = "")
{
	res.status = ErrorResponse::httpStatus(code);
	res.set_content(ErrorResponse::build(code, detail), "application/json");
}
