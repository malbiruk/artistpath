use artistpath::format_number;

#[test] 
fn test_format_number_basic() {
    assert_eq!(format_number(123), "123");
    assert_eq!(format_number(1234), "1,234");
    assert_eq!(format_number(12345), "12,345");
}

#[test]
fn test_format_number_large() {
    assert_eq!(format_number(123456), "123,456");
    assert_eq!(format_number(1234567), "1,234,567");
    assert_eq!(format_number(12345678), "12,345,678");
}

#[test]
fn test_format_number_edge_cases() {
    assert_eq!(format_number(0), "0");
    assert_eq!(format_number(1), "1");
    assert_eq!(format_number(12), "12");
    assert_eq!(format_number(100), "100");
    assert_eq!(format_number(1000), "1,000");
}