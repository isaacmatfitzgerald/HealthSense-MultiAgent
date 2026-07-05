create table hospitals_master
(
    hospital_id            varchar(20)                                                    not null
        primary key,
    hospital_name          varchar(255)                                                   not null,
    zip_code               int                                                            null,
    city                   varchar(100)                                                   null,
    state                  varchar(2)                                                     null,
    address                text                                                           null,
    phone                  varchar(20)                                                    null,
    email                  varchar(100)                                                   null,
    hospital_type          enum ('Teaching', 'Community', 'Specialty', 'Critical Access') null,
    bed_capacity           int                                                            null,
    trauma_level           enum ('Level I', 'Level II', 'Level III', 'Level IV', 'None')  null,
    emergency_services     tinyint(1) default 0                                           null,
    ambulance_available    tinyint(1) default 0                                           null,
    rating                 decimal(2, 1)                                                  null,
    specialties_count      int        default 0                                           null,
    lab_services_available tinyint(1) default 0                                           null,
    accreditation          varchar(100)                                                   null,
    ownership_type         enum ('Public', 'Private Non-Profit', 'Private For-Profit')    null,
    latitude               decimal(10, 8)                                                 null,
    longitude              decimal(11, 8)                                                 null,
    established_year       year                                                           null,
    website                varchar(255)                                                   null,
    created_at             timestamp  default CURRENT_TIMESTAMP                           null,
    updated_at             timestamp  default CURRENT_TIMESTAMP                           null on update CURRENT_TIMESTAMP,
    county_name            varchar(255)                                                   null,
    constraint hospitals_master_pk
        unique (hospital_id)
);

create table diagnostic_services_complete
(
    diagnostic_id             varchar(20)          not null
        primary key,
    hospital_id               varchar(20)          not null,
    test_category             varchar(100)         not null,
    test_name                 varchar(150)         not null,
    equipment_type            varchar(100)         null,
    availability_schedule     varchar(100)         null,
    cost_estimate             int                  null,
    preparation_required      tinyint(1) default 0 not null,
    results_timeframe         varchar(100)         null,
    insurance_accepted        varchar(255)         null,
    booking_required          tinyint(1) default 1 not null,
    interpretation_specialist varchar(100)         null,
    accuracy_rate             decimal(5, 2)        null,
    constraint diagnostic_services_complete_diagnostic_services_complete__fk
        foreign key (hospital_id) references hospitals_master (hospital_id),
    check (`cost_estimate` >= 0),
    check (`accuracy_rate` between 0 and 100)
);

create table emergencyServices
(
    emergency_id         varchar(20)                                                      not null
        primary key,
    hospital_id          varchar(20)                                                      not null,
    service_type         varchar(100)                                                     not null,
    current_capacity     int                                               default 0      null,
    max_capacity         int                                                              not null,
    avg_wait_time        int                                                              null,
    severity_handled     enum ('Critical', 'Moderate', 'Minor')                           not null,
    equipment_available  varchar(255)                                                     null,
    staff_on_duty        int                                               default 0      null,
    ambulance_fleet_size int                                               default 0      null,
    trauma_certification enum ('Level I', 'Level II', 'Level III', 'None') default 'None' null,
    last_status_update   datetime                                                         not null,
    coordinates          varchar(50)                                                      null,
    response_time_avg    int                                                              null,
    constraint emergency_services_enhanced_emergency_services_enhanced__fk
        foreign key (hospital_id) references hospitals_master (hospital_id),
    check (`current_capacity` >= 0),
    check (`max_capacity` > 0),
    check (`avg_wait_time` >= 0),
    check (`staff_on_duty` >= 0),
    check (`ambulance_fleet_size` >= 0),
    check (`response_time_avg` >= 0)
);

create table hospital_metrics
(
    metric_id          varchar(20)                                                not null
        primary key,
    hospital_id        varchar(20)                                                not null,
    metric_category    varchar(100)                                               not null,
    metric_name        varchar(150)                                               not null,
    current_value      decimal(8, 2)                                              not null,
    benchmark_value    decimal(8, 2)                                              null,
    percentile_rank    int                                                        null,
    trend_direction    enum ('Improving', 'Stable', 'Declining') default 'Stable' null,
    last_updated       date                                                       not null,
    data_source        varchar(100)                                               null,
    measurement_period varchar(50)                                                null,
    constraint hospital_metrics_hospital_metrics__fk
        foreign key (hospital_id) references hospitals_master (hospital_id),
    check (`percentile_rank` between 0 and 100)
);

create table hospital_services
(
    service_id            varchar(20)                                                 not null
        primary key,
    hospital_id           varchar(20)                                                 not null,
    service_category      varchar(100)                                                not null,
    service_name          varchar(150)                                                not null,
    availability_24_7     tinyint(1) default 0                                        not null,
    wait_time_avg_minutes int                                                         null,
    cost_tier             enum ('Low', 'Premium', 'Medium', 'High')                   null,
    equipment_level       enum ('Basic', 'Standard', 'Advanced', 'State-of-the-art')  null,
    staff_specialization  enum ('General', 'Research-level', 'Specialized', 'Expert') null,
    last_updated          date                                                        not null,
    capacity_current      int        default 0                                        null,
    capacity_max          int                                                         not null,
    constraint hospital_services_hospital_services__fk
        foreign key (hospital_id) references hospitals_master (hospital_id)
);

create index idx_location
    on hospitals_master (latitude, longitude);

create index idx_rating
    on hospitals_master (rating);

create index idx_type
    on hospitals_master (hospital_type);

create table insurance_compatibility
(
    insurance_id        varchar(20)                                  not null
        primary key,
    plan_name           varchar(150)                                 not null,
    provider_name       varchar(100)                                 not null,
    hospital_coverage   enum ('Full', 'Partial', 'None')             not null,
    doctor_coverage     enum ('Full', 'Copay', 'Deductible', 'None') not null,
    emergency_coverage  enum ('Full', 'Partial', 'None')             not null,
    diagnostic_coverage enum ('Full', 'Partial', 'None')             not null,
    network_type        enum ('HMO', 'PPO', 'EPO', 'Other')          not null
);

create table patient_journey_templates
(
    journey_id           varchar(20)  not null
        primary key,
    condition_type       varchar(100) not null,
    typical_path         varchar(255) not null,
    decision_points      varchar(255) null,
    required_specialists varchar(255) null,
    estimated_timeline   varchar(100) null,
    cost_factors         varchar(255) null,
    outcome_metrics      varchar(255) null
);

create table primary_specialty
(
    specialty_code        varchar(10)                                               not null
        primary key,
    specialty_name        varchar(100)                                              not null,
    category              enum ('Surgical', 'Medical', 'Diagnostic', 'Other')       not null,
    common_conditions     varchar(255)                                              null,
    typical_procedures    varchar(255)                                              null,
    urgency_level         enum ('Routine', 'Urgent', 'Emergency') default 'Routine' null,
    consultation_duration int                                                       null,
    referral_patterns     varchar(255)                                              null,
    check (`consultation_duration` > 0)
);

create table doctors
(
    doctor_id                varchar(20)                                 not null
        primary key,
    hospital_id              varchar(20)                                 not null,
    full_name                varchar(150)                                not null,
    first_name               varchar(50)                                 not null,
    last_name                varchar(50)                                 not null,
    primary_specialty        varchar(100)                                not null,
    secondary_specialization varchar(150)                                null,
    years_experience         int                                         null,
    education_level          enum ('MD', 'DO', 'MD/PhD', 'Other')        not null,
    board_certified          tinyint(1) default 0                        not null,
    languages_spoken         varchar(255)                                null,
    patient_rating           decimal(2, 1)                               null,
    consultation_fee         int                                         null,
    availability_type        enum ('Full-time', 'Part-time', 'Visiting') not null,
    emergency_on_call        tinyint(1) default 0                        not null,
    telemedicine_available   tinyint(1) default 0                        not null,
    contact_phone            varchar(30)                                 null,
    contact_email            varchar(100)                                null,
    constraint contact_email
        unique (contact_email),
    constraint doctors_enhanced___fk
        foreign key (primary_specialty) references primary_specialty (specialty_code),
    constraint doctors_enhanced_doctors_enhanced__fk
        foreign key (hospital_id) references hospitals_master (hospital_id),
    check (`years_experience` >= 0),
    check (`patient_rating` between 0 and 5)
);

create table doctoravailability
(
    slot_id                 varchar(20)                                         not null
        primary key,
    doctor_id               varchar(20)                                         not null,
    date                    date                                                not null,
    time_slot               time                                                not null,
    duration_minutes        int                                                 not null,
    appointment_type        enum ('Consultation', 'Follow-up', 'Emergency')     not null,
    is_available            tinyint(1)                           default 1      not null,
    booking_priority        enum ('High', 'Medium', 'Low')                      not null,
    patient_type_preference enum ('New', 'Existing', 'Referral') default 'New'  null,
    consultation_mode       enum ('In-person', 'Telemedicine', 'Hybrid')        not null,
    recurring_pattern       enum ('Weekly', 'Bi-weekly', 'None') default 'None' null,
    buffer_time             int                                  default 0      null,
    emergency_override      tinyint(1)                           default 0      not null,
    constraint fk_availability_doctor
        foreign key (doctor_id) references doctors (doctor_id)
            on update cascade on delete cascade,
    check (`duration_minutes` > 0),
    check (`buffer_time` >= 0)
);

create table appointments
(
    booking_id        varchar(20)                                                                       not null
        primary key,
    slot_id           varchar(20)                                                                       not null,
    doctor_id         varchar(20)                                                                       not null,
    patient_name      varchar(100)                                                                      not null,
    patient_phone     varchar(20)                                                                       null,
    patient_email     varchar(100)                                                                      null,
    appointment_date  date                                                                              not null,
    appointment_time  time                                                                              not null,
    appointment_type  enum ('Consultation', 'Follow-up', 'Emergency')         default 'Consultation'    null,
    consultation_mode enum ('In-person', 'Telemedicine', 'Hybrid')            default 'In-person'       null,
    booking_status    enum ('Confirmed', 'Cancelled', 'Completed', 'No-show') default 'Confirmed'       null,
    notes             text                                                                              null,
    created_at        timestamp                                               default CURRENT_TIMESTAMP null,
    updated_at        timestamp                                               default CURRENT_TIMESTAMP null on update CURRENT_TIMESTAMP,
    constraint appointments_ibfk_1
        foreign key (slot_id) references doctoravailability (slot_id)
            on delete cascade,
    constraint appointments_ibfk_2
        foreign key (doctor_id) references doctors (doctor_id)
            on delete cascade
);

create index idx_appointment_date
    on appointments (appointment_date);

create index idx_booking_status
    on appointments (booking_status);

create index idx_doctor_date
    on appointments (doctor_id, appointment_date);

create index idx_patient_email
    on appointments (patient_email);

create index slot_id
    on appointments (slot_id);

